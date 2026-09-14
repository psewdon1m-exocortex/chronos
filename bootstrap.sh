#!/bin/sh
set -eu
service='chronos'
version='__HEAD_BOOTSTRAP_RELEASE_VERSION__'
public_key='__HEAD_BOOTSTRAP_PUBLIC_KEY_BASE64__'
repository='psewdon1m-exocortex/chronos'
target="/opt/exocortex/$service"
fail() { printf '%s\n' "$service bootstrap: $*" >&2; exit 1; }
[ "$#" -eq 0 ] || fail 'This exact-version bootstrap takes no arguments'
printf '%s' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' || fail 'Use bootstrap.sh from a service-qualified release asset'
[ "$(id -u)" -eq 0 ] || fail 'Run as root'
[ ! -f "$target/.env" ] && [ ! -f "$target/install.sh" ] || fail 'Installation already staged. Use its install command or the application Updater; bootstrap never replaces an existing installation'
for cmd in curl openssl python3; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"; done
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
printf '%s' "$public_key" | openssl base64 -d -A >"$work/public.pem"
base="https://github.com/$repository/releases/download/$service-v$version"
fetch() { curl -fL --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 3 --connect-timeout 10 --max-time 300 --max-filesize 268435456 -o "$2" "$1"; }
fetch "$base/$service-release.json" "$work/manifest.json"
fetch "$base/$service-release.json.sig.json" "$work/signature.json"
python3 - "$work/manifest.json" "$work/signature.json" "$work/public.pem" <<'VERIFY_SIGNATURE'
"""Verify a release with the explicit public key selected by the caller."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

manifest, envelope, trust = map(Path, sys.argv[1:])
if manifest.stat().st_size > 2 * 1024 * 1024 or envelope.stat().st_size > 16384 or trust.stat().st_size > 16384:
    raise SystemExit("Release signature input exceeds limit")
signed = json.loads(envelope.read_text(encoding="utf8"))
if signed.get("schema") != "exocortex.release-signature.v1" or signed.get("algorithm") != "RSA-PSS-SHA256":
    raise SystemExit("Unsupported release signature")
public = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(trust), "-outform", "DER"], check=True, capture_output=True).stdout
if hashlib.sha256(public).hexdigest() != signed.get("key_id"):
    raise SystemExit("Release signer is not trusted")
description = subprocess.run(["openssl", "rsa", "-pubin", "-in", str(trust), "-text", "-noout"], check=True, capture_output=True, text=True).stdout
bits = re.search(r"Public-Key: \((\d+) bit\)", description)
if not bits or int(bits[1]) < 3072:
    raise SystemExit("Release trust requires RSA with at least 3072 bits")
with tempfile.TemporaryDirectory(prefix="exocortex-signature-") as temporary:
    signature = Path(temporary) / "signature.bin"
    signature.write_bytes(base64.b64decode(signed["signature"], validate=True))
    subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(trust), "-signature", str(signature), "-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:32", str(manifest)], check=True)

VERIFY_SIGNATURE
bundle="$service-$version-compose.tar.gz"
fetch "$base/$bundle" "$work/bundle.tar.gz"
python3 - "$work" "$service" "$version" "$base/$bundle" <<'VALIDATE_BUNDLE'
import hashlib, json, pathlib, re, sys, tarfile
work, service, version, expected_url = pathlib.Path(sys.argv[1]), *sys.argv[2:]
manifest = json.loads((work / 'manifest.json').read_bytes())
if manifest.get('schema_version') != 1 or manifest.get('service') != service or manifest.get('version') != version: raise SystemExit('Release identity mismatch')
bundle = manifest.get('compose_bundle', {})
image = manifest.get('image', {})
if bundle.get('url') != expected_url or not re.fullmatch(r'[a-f0-9]{64}', bundle.get('sha256', '')): raise SystemExit('Invalid release bundle identity')
if not re.fullmatch(r'ghcr.io/[a-z0-9._/-]+', image.get('reference', '')) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image.get('digest', '')): raise SystemExit('Invalid immutable image')
if hashlib.sha256((work / 'bundle.tar.gz').read_bytes()).hexdigest() != bundle['sha256']: raise SystemExit('Bundle checksum mismatch')
stage = work / 'stage'
stage.mkdir()
with tarfile.open(work / 'bundle.tar.gz', 'r:gz') as archive:
    members = archive.getmembers()
    if len(members) > 512 or sum(m.size for m in members) > 512 * 1024 * 1024: raise SystemExit('Bundle limit exceeded')
    seen = set()
    for m in members:
        name = m.name.removeprefix('./').rstrip('/')
        if name in {'', '.'} and m.isdir(): continue
        p = pathlib.PurePosixPath(name)
        if not name or '\\' in name or p.is_absolute() or '..' in p.parts or any(ord(c) < 32 for c in name) or name in seen or not (m.isfile() or m.isdir()): raise SystemExit('Unsafe or duplicate archive member')
        seen.add(name)
    for m in members:
        name = m.name.removeprefix('./').rstrip('/')
        if name in {'', '.'}: continue
        destination = stage / name
        if m.isdir(): destination.mkdir(parents=True, exist_ok=True); continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(m) as source: destination.write_bytes(source.read())
        destination.chmod(0o755 if name.endswith('.sh') or name.endswith('updater-linux-amd64') else 0o644)
for required in ['compose.production.yaml', 'compose.updater.yaml', '.env.example', 'install.sh', 'updater/install.sh', 'updater/updater-linux-amd64', 'updater/systemd/updater.service', *['updater/release-trust/' + s + '.pem' for s in ['updater','neptune','gryphon']]]:
    if not (stage / required).is_file(): raise SystemExit('Incomplete release: ' + required)
env = dict(line.split('=',1) for line in (stage / '.env.example').read_text().splitlines() if '=' in line and not line.startswith('#'))
prefix = service.upper()
if env.get(prefix + '_VERSION') != version or env.get(prefix + '_IMAGE') != image['reference'] + '@' + image['digest']: raise SystemExit('Bundle environment does not match signed manifest')
VALIDATE_BUNDLE
trust=/etc/exocortex/release-trust
if [ -f "$trust/$service.pem" ]; then cmp -s "$trust/$service.pem" "$work/public.pem" || fail 'Pinned release key differs; explicit trust rotation is required'; fi
install -d -m 0755 "$trust"
install -m 0644 "$work/public.pem" "$trust/$service.pem"
install -d -m 0750 "$target"
cp -a "$work/stage/." "$target/"
chown -R root:root "$target"
chmod 0755 "$target/install.sh"
"$target/install.sh" prepare
printf '%s\n' "Verified $service $version." "Edit: sudoedit $target/.env" "Run: sudo chmod 600 $target/.env && sudo $service-install && sudo $service-install status" 'Configure server nginx and verify public access after installation.'
