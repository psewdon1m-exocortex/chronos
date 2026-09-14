#!/usr/bin/env python3
"""Anonymous exact-tag asset and derived-trust verification before promotion."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

root=Path(__file__).resolve().parents[1]
assets=Path(sys.argv[1]).resolve()
service="chronos" if (root/"web/package.json").exists() else "laboratory"
manifest=json.loads((assets/(service+"-release.json")).read_bytes())
version=manifest["version"];tag=service+"-v"+version
assert manifest["service"]==service and re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?",version)
repository="psewdon1m-exocortex/"+service
base=f"https://github.com/{repository}/releases/download/{tag}"
names=[service+"-release.json",service+"-release.json.sig.json",service+".pem","bootstrap.sh",f"{service}-{version}-compose.tar.gz"]
with tempfile.TemporaryDirectory() as directory:
    downloaded=Path(directory)
    for name in names:
        for attempt in range(10):
            try:
                # No Authorization header, ambient GitHub token or authenticated CLI.
                with urllib.request.urlopen(base+"/"+name,timeout=60) as response:
                    data=response.read(268435457)
                if len(data)>268435456: raise ValueError("Asset exceeds limit")
                break
            except Exception:
                if attempt==9: raise
                time.sleep(2)
        assert hashlib.sha256(data).digest()==hashlib.sha256((assets/name).read_bytes()).digest(),name+" differs externally"
        (downloaded/name).write_bytes(data)
    subprocess.run([sys.executable,str(root/"scripts/verify-release-manifest.py"),str(downloaded/(service+"-release.json")),str(downloaded/(service+"-release.json.sig.json")),str(assets/(service+".pem"))],check=True)
    bootstrap=(downloaded/"bootstrap.sh").read_text()
    assert "PRIVATE KEY" not in bootstrap and "__HEAD_BOOTSTRAP_" not in bootstrap
    assert "version='"+version+"'" in bootstrap
    import base64
    embedded=base64.b64decode(re.search(r"public_key='([^']+)'",bootstrap)[1],validate=True)
    assert embedded==(assets/(service+".pem")).read_bytes()
    expected=manifest["compose_bundle"]["sha256"]
    assert hashlib.sha256((downloaded/names[-1]).read_bytes()).hexdigest()==expected
    remote=subprocess.check_output(["git","ls-remote","--exit-code","origin","refs/tags/"+tag,"refs/tags/"+tag+"^{}"],cwd=root,text=True)
    hashes=[line.split()[0] for line in remote.splitlines()]
    local=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    assert hashes and hashes[-1]==local,"Published tag points to a different commit"
print(json.dumps({"result":"PASS","tag":tag,"assets":names,"anonymous":True,"embedded_public_trust":True,"revision":local}))
