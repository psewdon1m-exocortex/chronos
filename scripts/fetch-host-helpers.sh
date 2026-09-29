#!/usr/bin/env bash
set -euo pipefail

# Run only after the exact pinned Updater installer was verified and extracted.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
updater_bundle="${UPDATER_BUNDLE_DIR:-$root/.release-inputs/updater}"
helper_bundles="${HOST_HELPER_BUNDLE_DIR:-$root/.release-inputs/helpers}"
"$updater_bundle/updater-linux-amd64" host capabilities | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("schema")=="exocortex.updater.host-dependencies.v1" and d.get("api_version")==1'
for helper in "$@"; do
  case "$helper" in neptune|gryphon) ;; *) echo "Unknown host helper: $helper" >&2; exit 2 ;; esac
  version="$(tr -d '[:space:]' < "$root/.release/$helper.version")"
  expected_sha="$(tr -d '[:space:]' < "$root/.release/$helper.sha256")"
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$expected_sha" =~ ^[a-f0-9]{64}$ ]] || { echo "Invalid $helper release pin" >&2; exit 2; }
  destination="$helper_bundles/$helper"
  mkdir -p "$destination"
  tag="$helper-v$version"
  repository="psewdon1m-exocortex/$helper"
  gh release view "$tag" --repo "$repository" --json isDraft,isPrerelease,tagName --jq 'select(.isDraft == false and .isPrerelease == false and .tagName == "'"$tag"'") | .tagName' | grep -Fx "$tag"
  manifest="$helper-linux-release-linux-x64.json"
  gh release download "$tag" --repo "$repository" --dir "$destination" --pattern "$manifest" --pattern "$manifest.sig.json"
  artifact="$(python3 - "$destination/$manifest" "$destination/$manifest.sig.json" "$updater_bundle/release-trust/$helper.pem" "$helper" "$version" "$expected_sha" <<'PY'
import base64, hashlib, json, pathlib, re, subprocess, sys, tempfile
manifest, envelope, trust = map(pathlib.Path, sys.argv[1:4])
helper, version, expected_sha = sys.argv[4:]
body = manifest.read_bytes()
signature = json.loads(envelope.read_bytes())
data = json.loads(body)
assert len(body) <= 2 * 1024 * 1024 and envelope.stat().st_size <= 16384
assert signature.get("schema") == "exocortex.release-signature.v1" and signature.get("algorithm") == "RSA-PSS-SHA256"
der = subprocess.check_output(["openssl", "pkey", "-pubin", "-in", str(trust), "-outform", "DER"])
assert hashlib.sha256(der).hexdigest() == signature.get("key_id")
assert data.get("schema") == "exocortex." + helper + ".release.v1"
assert data.get("product") == helper + "-linux" and data.get("version") == version and data.get("runtime") == "linux-x64"
assert data.get("sha256") == expected_sha
artifact = data.get("artifact", "")
assert re.fullmatch(r"[A-Za-z0-9_.-]+\.tar\.gz", artifact)
with tempfile.TemporaryDirectory() as temporary:
    signed = pathlib.Path(temporary) / "signature"
    signed.write_bytes(base64.b64decode(signature["signature"], validate=True))
    subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(trust), "-signature", str(signed),
                    "-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:32", str(manifest)],
                   check=True, stdout=subprocess.DEVNULL)
print(artifact)
PY
)"
  gh release download "$tag" --repo "$repository" --dir "$destination" --pattern "$artifact"
  printf '%s  %s\n' "$expected_sha" "$destination/$artifact" | sha256sum -c -
  if [[ "$helper" == gryphon ]]; then
    tar -xOzf "$destination/$artifact" ./package.json | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p.get("hostDependencyProtocol")==1, "Gryphon release cannot start without Kernel"'
  fi
done
