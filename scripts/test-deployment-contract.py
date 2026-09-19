#!/usr/bin/env python3
"""Validate the head's rendered production contract and activation template.
These checks qualify templates, not the operator's DNS, TLS or credentials.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

root=Path(__file__).resolve().parents[1]
service="chronos" if (root/"web/package.json").exists() else "laboratory"
prefix=service.upper();port=18280 if service=="chronos" else 18380
version=json.loads((root/("web/package.json" if service=="chronos" else "services/api/package.json")).read_text())["version"]
values=dict(line.split("=",1) for line in (root/".env.example").read_text().splitlines() if "=" in line and not line.startswith("#"))
assert values[prefix+"_VERSION"]==version
assert set(key for key in values if "CHANGE_ME" in values[key] and key in ["KERNEL_URL","KERNEL_SERVICE_TOKEN",prefix+"_ACCESS_KEY"])=={"KERNEL_URL","KERNEL_SERVICE_TOKEN",prefix+"_ACCESS_KEY"}
gid=1000
for key,value in values.items():
    if "CHANGE_ME" in value or value.startswith("replace-"):
        gid+=1
        values[key]=str(gid) if "GID" in key else "synthetic-contract-value-012345678901234567890"
values.update({"KERNEL_URL":"https://kernel.example.test",prefix+"_IMAGE":"ghcr.io/psewdon1m-exocortex/"+service+"@sha256:"+"a"*64})
with tempfile.TemporaryDirectory() as directory:
    env=Path(directory)/"head.env";env.write_text("\n".join(k+"="+v for k,v in values.items()))
    clean_env={k:v for k,v in os.environ.items() if k not in values}
    rendered=json.loads(subprocess.check_output(["docker","compose","--env-file",str(env),"-f",str(root/"compose.production.yaml"),"config","--format","json"],cwd=root,env=clean_env,text=True))
head=rendered["services"][service]
assert head["image"].endswith("@sha256:"+"a"*64)
assert head["environment"][prefix+"_VERSION"]==version
assert len(head["ports"])==1 and head["ports"][0]["host_ip"]=="127.0.0.1" and int(head["ports"][0]["published"])==port
assert head["read_only"] and "ALL" in head["cap_drop"]
assert "no-new-privileges:true" in head["security_opt"]
assert head["environment"][prefix+"_COOKIE_SECURE"]=="true"
assert head["environment"][prefix+"_TRUSTED_PROXY_IPS"] not in ["*","0.0.0.0/0"]
assert not any(re.search(r"nginx|coturn",key,re.I) for key in rendered["services"])
assert "OPERATOR_CIDR" not in (root/"compose.production.yaml").read_text()
assert not any("CONTENT_GITHUB_TOKEN" in key or "SATURN_CLIENT_TOKEN" in key for key in head["environment"])
installer=(root/"install.sh").read_text()
assert "copy_local_kernel_bootstrap" not in installer and "/opt/exocortex/kernel/.env" not in installer
assert "docker inspect --format" in installer and prefix+"_TRUSTED_PROXY_IPS" in installer
# Exercise the actual install fragment against a created but never started
# container: Docker leaves its endpoint Gateway empty until start.
probe="head-gateway-test-"+uuid.uuid4().hex[:12]
container=probe+"-container"
try:
    subprocess.run(["docker","network","create",probe],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(["docker","create","--name",container,"--network",probe,"alpine:3.23","true"],check=True,stdout=subprocess.DEVNULL)
    endpoint=json.loads(subprocess.check_output(["docker","inspect",container],text=True))[0]
    assert not endpoint["NetworkSettings"]["Networks"][probe]["Gateway"]
    start=installer.index("  networks=$(docker inspect")
    end=installer.index('  [ -n "$gateways" ]',start)
    fragment=installer[start:end]+'\nprintf "%s" "$gateways"\n'
    gateways=subprocess.check_output(["sh","-c",fragment],env={**os.environ,"container":container},text=True)
    network=json.loads(subprocess.check_output(["docker","network","inspect",probe],text=True))[0]
    assert gateways=="".join(","+item["Gateway"] for item in network["IPAM"]["Config"] if item.get("Gateway"))
    assert gateways
finally:
    subprocess.run(["docker","rm","-f",container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(["docker","network","rm",probe],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
assert "release-trust" in (root/("bootstrap.sh" if service=="chronos" else "scripts/bootstrap.sh")).read_text()
runbook=(root/"DEPLOYMENT.md").read_text()
for term in ["NOT_RUN","nginx -t","two independent","rollback","overdue","failure domain","GitHub","Neptune",".env","SHA-256","128 MiB"]:
    assert term.lower() in runbook.lower(),term
nginx=(root/"nginx.server.example.conf").read_text()
for term in ["server_name", "ssl_certificate_key", "client_max_body_size", "proxy_request_buffering off", "proxy_connect_timeout", "proxy_read_timeout", "X-Forwarded-For $remote_addr", "127.0.0.1:"+str(port), "/api/internal/"]:
    assert term in nginx,term
policy=json.loads((root/".release/known-problems-policy.json").read_text())
assert len(policy["checks"])==88 and len(policy["catalog_revision"])==40
assert (root/".release/updater.version").read_text().strip()=="0.5.0"
for script in ["install.sh", "bootstrap.sh" if service=="chronos" else "scripts/bootstrap.sh"]:
    subprocess.run(["sh","-n",str(root/script)],check=True)
print(json.dumps({"service":service,"version":version,"result":"PASS","scope":"rendered head Compose, own installer/env/trust, operator activation and nginx templates","production_activation":"NOT_RUN"}))
