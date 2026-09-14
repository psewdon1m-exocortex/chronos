#!/usr/bin/env python3
"""Version-bound Part 12 evidence gate; UNKNOWN never qualifies a release.

Receipts are emitted only by --record after executing a command. They bind the
command, output checksum, source revision, CI run and immutable policy bytes.
Deployment activation is deliberately a separate NOT_RUN record.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".release/known-problems-policy.json"

def digest(data): return hashlib.sha256(data).hexdigest()
def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("Duplicate JSON key: "+key)
        result[key]=value
    return result
def read_json(path): return json.loads(path.read_text(encoding="utf-8"),object_pairs_hook=unique_object)
def git(*args): return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
def load_catalog(policy, directory):
    raw = directory / "catalog.md"
    if not raw.exists():
        url = f"https://raw.githubusercontent.com/psewdon1m-exocortex/general/{policy['catalog_revision']}/{policy['remote_path']}"
        with urllib.request.urlopen(url, timeout=30) as response: data = response.read(2 * 1024 * 1024 + 1)
        if len(data)>2*1024*1024 or digest(data)!=policy["catalog_sha256"]: raise ValueError("Pinned policy checksum mismatch")
        raw.write_bytes(data)
    data=raw.read_bytes()
    if digest(data)!=policy["catalog_sha256"]: raise ValueError("Stale or altered policy catalog")
    rows=[]
    for line in data.decode("utf8").splitlines():
        match=re.match(r"\| \*\*([A-Z]+-\d{2})\*\* \| (.+) \| (.+) \|$",line)
        if match: rows.append(match.groups())
    ids=[row[0] for row in rows]
    if not ids or len(ids)!=len(set(ids)) or len(ids)!=policy["active_ids"]: raise ValueError("Invalid catalog ID inventory")
    for row in rows:
        if not row[1].strip() or not row[2].strip(): raise ValueError("Empty problem/solution cell")
    # Only links to documents from this same immutable central revision are local.
    for link in sorted(set(re.findall(r"\]\(([^)]+)\)",data.decode("utf8")))):
        if link.startswith("./") and not re.fullmatch(r"\./PART_\d{2}_[A-Z_]+\.md(?:#[^ ]+)?",link): raise ValueError("Unexpected local policy link")
        if link.startswith("./"):
            filename=link[2:].split("#",1)[0]
            cached=directory/filename
            if not cached.exists():
                url=f"https://raw.githubusercontent.com/psewdon1m-exocortex/general/{policy['catalog_revision']}/{filename}"
                with urllib.request.urlopen(url,timeout=30) as response: linked=response.read(2*1024*1024+1)
                if len(linked)>2*1024*1024 or not linked.startswith(b"# "): raise ValueError("Invalid linked policy document")
                cached.write_bytes(linked)
    return ids

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--phase",choices=["structure","pre-signing","final"],default="structure")
    parser.add_argument("--evidence-dir",default=".release-evidence")
    parser.add_argument("--report",default="known-problems-report.json")
    parser.add_argument("--record")
    parser.add_argument("--command",nargs=argparse.REMAINDER)
    args=parser.parse_args()
    policy=read_json(POLICY);directory=(ROOT/args.evidence_dir).resolve();directory.mkdir(parents=True,exist_ok=True)
    if not directory.is_relative_to(ROOT): raise ValueError("Evidence must remain inside the project")
    revision=git("rev-parse","HEAD")
    if not re.fullmatch(r"[a-f0-9]{40}",policy["catalog_revision"]): raise ValueError("Policy must pin a full commit SHA")
    ids=load_catalog(policy,directory)
    if set(ids)!=set(policy["checks"]): raise ValueError("Applicability plan must contain every active ID exactly once")
    run_id=os.getenv("GITHUB_RUN_ID","local")+":"+os.getenv("GITHUB_RUN_ATTEMPT","1")
    identity={"revision":revision,"catalog_sha256":policy["catalog_sha256"],"run_id":run_id}
    if args.record:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}",args.record) or not args.command: raise ValueError("A receipt needs a named executable command")
        result=subprocess.run(args.command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        log=directory/(args.record+".log");log.write_bytes(result.stdout)
        receipt={**identity,"case":args.record,"command":args.command,"exit_code":result.returncode,"log":log.name,"log_sha256":digest(result.stdout)}
        (directory/(args.record+".json")).write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
        sys.stdout.buffer.write(result.stdout)
        return result.returncode
    checks=[]
    for problem_id in ids:
        entry=policy["checks"][problem_id]
        status="UNKNOWN";reason=None;evidence=[]
        if entry.get("not_applicable"):
            reason=entry["not_applicable"]
            paths=entry.get("paths",[])
            if len(reason)<50 or not paths or any(not (ROOT/p).exists() for p in paths): raise ValueError("Unexplained N/A: "+problem_id)
            status="N/A"
        else:
            if not entry.get("cases") or any(not re.fullmatch(r"[a-z][a-z0-9-]{0,40}",case) for case in entry["cases"]): raise ValueError("Missing or invalid executable cases: "+problem_id)
            good=True
            for case in entry["cases"]:
                receipt_path=directory/(case+".json")
                if not receipt_path.exists(): good=False;continue
                receipt=read_json(receipt_path);log=directory/receipt.get("log","")
                if log.parent!=directory or not log.is_file() or any(receipt.get(k)!=v for k,v in identity.items()): good=False;continue
                if receipt.get("case")!=case or not receipt.get("command") or digest(log.read_bytes())!=receipt.get("log_sha256"): good=False;continue
                if receipt.get("exit_code")!=0: status="FAIL";good=False
                evidence.append({"receipt":str(receipt_path.relative_to(ROOT)),"command":receipt["command"],"log_sha256":receipt["log_sha256"]})
            if good: status="PASS"
        deferred=entry.get("phase")=="final" and args.phase!="final"
        checks.append({"id":problem_id,"status":status,"phase":entry.get("phase","pre-signing"),"deferred":deferred,"evidence":evidence,"reason":reason,"scope":entry["scope"]})
    unresolved=[r["id"] for r in checks if r["status"] in ["FAIL","UNKNOWN"] and not r["deferred"]]
    tag=os.getenv("GITHUB_REF_NAME","")
    if args.phase!="structure":
        if not re.fullmatch(re.escape(policy["service"])+r"-v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?",tag): raise ValueError("Release qualification requires an exact service-qualified tag")
        if git("rev-parse",tag+"^{commit}")!=revision: raise ValueError("Tag/revision mismatch")
        if git("status","--porcelain","--untracked-files=no"): raise ValueError("Dirty source cannot qualify a release")
    report={"schema_version":1,"service":policy["service"],**identity,"release_tag":tag or None,"phase":args.phase,"catalog_repository":"https://github.com/psewdon1m-exocortex/general","catalog_revision":policy["catalog_revision"],"catalog_path":policy["remote_path"],"checks":checks,"release_qualification":args.phase=="final" and not unresolved,"deployment_activation":{"status":"NOT_RUN","reason":"Production DNS/TLS, real provider credentials, external reachability and installed agent versions require the operator activation checks in DEPLOYMENT.md."}}
    (ROOT/args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Part 12 {args.phase}: {len(checks)} IDs, {len(unresolved)} unresolved, qualification={report['release_qualification']}")
    return 1 if unresolved and args.phase!="structure" else 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as error: print("Part 12 gate:",error,file=sys.stderr);sys.exit(1)
