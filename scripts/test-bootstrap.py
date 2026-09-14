#!/usr/bin/env python3
"""Real packager/signature/bootstrap/prepare regression in a disposable root container.

Only the download transport and bundled helper executable are fixtures. No
systemd, image pull, production credentials or public deployment is claimed.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
service = "chronos" if (root / "web/package.json").exists() else "laboratory"
package = root / ("web/package.json" if service == "chronos" else "services/api/package.json")
version = json.loads(package.read_text())["version"]
target = Path("/opt/exocortex") / service
trust = Path("/etc/exocortex/release-trust") / (service + ".pem")
if not Path("/.dockerenv").exists() or os.geteuid() != 0:
    raise SystemExit("Run only as root in a disposable Docker container")
if target.exists() or trust.exists():
    raise SystemExit("Test requires an empty disposable installation root")
checks = []

def run(args, *, env=None, expected=0, cwd=root):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if (result.returncode == 0) != (expected == 0):
        raise AssertionError(f"{args[0]} exit {result.returncode}: {result.stdout[-2000:]} {result.stderr[-2000:]}")
    return result

with tempfile.TemporaryDirectory(prefix="head-bootstrap-test-") as directory:
    work = Path(directory)
    private = work / "test-signing.pem"
    run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(private)])
    env = {**os.environ, "RELEASE_SIGNING_KEY_FILE": str(private)}
    output = work / "artifacts"
    run(["node", "scripts/sign-release.mjs", "--export-public-key", str(output / (service + ".pem"))], env=env)
    helper = work / "updater"
    (helper / "release-trust").mkdir(parents=True)
    (helper / "systemd").mkdir()
    (helper / "install.sh").write_text("#!/bin/sh\nexit 0\n")
    (helper / "updater-linux-amd64").write_text("#!/bin/sh\necho synthetic-helper\n")
    (helper / "systemd/updater.service").write_text("[Service]\nExecStart=/usr/bin/updater\n")
    for scope in ["updater", "neptune", "gryphon"]:
        shutil.copyfile(output / (service + ".pem"), helper / "release-trust" / (scope + ".pem"))
    env.update({"GITHUB_REPOSITORY": "psewdon1m-exocortex/" + service,
                "IMAGE_REFERENCE": "ghcr.io/psewdon1m-exocortex/" + service,
                "IMAGE_DIGEST": "sha256:" + "a" * 64,
                "UPDATER_BUNDLE_DIR": str(helper),
                "UPDATER_BUNDLE_VERSION": (root / ".release/updater.version").read_text().strip()})
    run(["bash", "scripts/build-release.sh", version, str(output)], env=env)
    manifest = output / (service + "-release.json")
    run(["node", "scripts/sign-release.mjs", str(manifest)], env=env)
    assets = {file.name: file.read_bytes() for file in output.iterdir()}
    download = work / "bin"
    download.mkdir()
    curl = download / "curl"
    curl.write_text("#!/usr/bin/env python3\nimport os,sys,shutil\nfrom pathlib import Path\na=sys.argv[1:];url=a[-1];base=os.environ['FIXTURE_BASE']\nif not url.startswith(base+'/') or '/' in url[len(base)+1:]:sys.exit(22)\nshutil.copyfile(Path(os.environ['FIXTURE_ASSETS'])/url.split('/')[-1],a[a.index('-o')+1])\n")
    curl.chmod(0o755)
    env.update({"PATH": str(download) + ":" + os.environ["PATH"], "FIXTURE_ASSETS": str(output),
                "FIXTURE_BASE": f"https://github.com/psewdon1m-exocortex/{service}/releases/download/{service}-v{version}"})
    bootstrap = output / "bootstrap.sh"

    def reset():
        # Both exact targets are fixed above and this process requires /.dockerenv.
        if target.exists(): shutil.rmtree(target)
        trust.unlink(missing_ok=True)
        for name, data in assets.items(): (output / name).write_bytes(data)

    def check(name, callback):
        reset()
        callback()
        checks.append({"name": name, "result": "PASS"})
        print("PASS:", name, flush=True)

    def clean_install():
        run(["sh", str(bootstrap)], env=env)
        contents = (target / ".env").read_text()
        assert (target / ".env").stat().st_mode & 0o777 == 0o600
        assert f"{service.upper()}_ACCESS_KEY=CHANGE_ME" in contents
        assert "KERNEL_SERVICE_TOKEN=CHANGE_ME" in contents
        assert "@sha256:" + "a" * 64 in contents
        assert trust.read_bytes() == assets[service + ".pem"]
        assert "PRIVATE KEY" not in bootstrap.read_text()
        for scope in ["updater", "neptune", "gryphon"]:
            assert (target / "updater/release-trust" / (scope + ".pem")).read_bytes() == assets[service + ".pem"]
        assert (Path("/usr/local/sbin") / (service + "-install")).exists()
        before = hashlib.sha256((target / ".env").read_bytes()).digest()
        run(["sh", str(bootstrap)], env=env, expected=1)
        assert hashlib.sha256((target / ".env").read_bytes()).digest() == before
        run([str(target / "install.sh"), "prepare"], env=env)
        assert hashlib.sha256((target / ".env").read_bytes()).digest() == before
    check("exact-version bootstrap creates private own env, public trust and command; rerun preserves state", clean_install)

    def altered_signature():
        manifest.write_bytes(manifest.read_bytes() + b" ")
        run(["sh", str(bootstrap)], env=env, expected=1)
        assert not target.exists()
    check("altered signed manifest rejected before staging", altered_signature)

    def identity():
        body=json.loads(manifest.read_text());body["version"]="99.99.99";manifest.write_text(json.dumps(body))
        run(["node","scripts/sign-release.mjs",str(manifest)],env=env)
        run(["sh",str(bootstrap)],env=env,expected=1)
        assert not target.exists()
    check("valid signature cannot override exact selected release identity", identity)

    bundle = output / f"{service}-{version}-compose.tar.gz"
    def corrupt():
        data=bytearray(bundle.read_bytes());data[-15]^=255;bundle.write_bytes(data)
        run(["sh",str(bootstrap)],env=env,expected=1)
        assert not target.exists()
    check("bundle checksum mismatch rejected", corrupt)

    def unsafe():
        with tarfile.open(bundle,"w:gz") as archive:
            member=tarfile.TarInfo("../escape");member.size=1;archive.addfile(member,io.BytesIO(b"x"))
        body=json.loads(manifest.read_text());body["compose_bundle"]["sha256"]=hashlib.sha256(bundle.read_bytes()).hexdigest();manifest.write_text(json.dumps(body))
        run(["node","scripts/sign-release.mjs",str(manifest)],env=env)
        run(["sh",str(bootstrap)],env=env,expected=1)
        assert not target.exists()
    check("signed traversal archive rejected", unsafe)

    def foreign():
        trust.parent.mkdir(parents=True,exist_ok=True);trust.write_text("previous explicit public trust\n")
        run(["sh",str(bootstrap)],env=env,expected=1)
        assert trust.read_text()=="previous explicit public trust\n"
        assert not target.exists()
    check("existing foreign trust never silently replaced", foreign)
    reset()
print(json.dumps({"service":service,"version":version,"checks":checks,"transport":"fixture","systemd_tested":False}))
