#!/usr/bin/env sh
set -eu

REPOSITORY="psewdon1m-exocortex/chronos"
INSTALL_DIR="${CHRONOS_INSTALL_DIR:-/opt/exocortex/chronos}"
API_URL="https://api.github.com/repos/$REPOSITORY/releases?per_page=100"

[ "$(id -u)" -eq 0 ] || { echo "Run the Chronos bootstrap as root." >&2; exit 4; }
[ ! -f "$INSTALL_DIR/.env" ] || {
  echo "Chronos is already prepared at $INSTALL_DIR. Use the Settings updater for an existing installation." >&2
  exit 5
}

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl openssl python3 tar

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT INT TERM
curl -fsSL --retry 3 --connect-timeout 10 "$API_URL" -o "$temporary/releases.json"

manifest_url=$(python3 - "$temporary/releases.json" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    releases = json.load(handle)
candidates = []
for release in releases:
    match = re.fullmatch(r"chronos-v(\d+)\.(\d+)\.(\d+)", str(release.get("tag_name") or ""))
    if match and not release.get("draft") and not release.get("prerelease"):
        candidates.append((tuple(map(int, match.groups())), release))
if not candidates:
    raise SystemExit("No stable chronos-v* release is available.")
release = max(candidates, key=lambda item: item[0])[1]
for asset in release.get("assets") or []:
    if asset.get("name") == "chronos-release.json":
        print(asset["browser_download_url"])
        break
else:
    raise SystemExit("The selected Chronos release has no manifest.")
PY
)
curl -fsSL --retry 3 --connect-timeout 10 "$manifest_url" -o "$temporary/manifest.json"

fields=$(python3 - "$temporary/manifest.json" <<'PY'
import json, re, sys
from urllib.parse import urlparse
with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
bundle = manifest.get("compose_bundle") or {}
image = manifest.get("image") or {}
version = str(manifest.get("version") or "")
url = str(bundle.get("url") or "")
checksum = str(bundle.get("sha256") or "").removeprefix("sha256:").lower()
reference = str(image.get("reference") or "")
digest = str(image.get("digest") or "")
parsed = urlparse(url)
if manifest.get("schema_version") != 1 or manifest.get("service") != "chronos":
    raise SystemExit("Invalid Chronos release manifest identity.")
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    raise SystemExit("Invalid Chronos release version.")
if parsed.scheme != "https" or parsed.hostname != "github.com":
    raise SystemExit("Chronos bundle must be downloaded from GitHub over HTTPS.")
if not re.fullmatch(r"[a-f0-9]{64}", checksum):
    raise SystemExit("Invalid Chronos bundle checksum.")
if not reference.startswith("ghcr.io/") or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
    raise SystemExit("Invalid immutable Chronos image reference.")
print(version)
print(url)
print(checksum)
print(reference + "@" + digest)
PY
)
version=$(printf '%s\n' "$fields" | sed -n '1p')
bundle_url=$(printf '%s\n' "$fields" | sed -n '2p')
bundle_sha=$(printf '%s\n' "$fields" | sed -n '3p')
image=$(printf '%s\n' "$fields" | sed -n '4p')

curl -fsSL --retry 3 --connect-timeout 10 "$bundle_url" -o "$temporary/chronos.tar.gz"
printf '%s  %s\n' "$bundle_sha" "$temporary/chronos.tar.gz" | sha256sum -c -
if tar -tzf "$temporary/chronos.tar.gz" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "Chronos release archive contains an unsafe path." >&2
  exit 14
fi
mkdir -p "$temporary/stage" "$INSTALL_DIR"
tar -xzf "$temporary/chronos.tar.gz" -C "$temporary/stage" --no-same-owner --no-same-permissions
cp -a "$temporary/stage/." "$INSTALL_DIR/"
chown -R root:root "$INSTALL_DIR"
chmod 0755 "$INSTALL_DIR/install.sh"
CHRONOS_RELEASE_VERSION="$version" CHRONOS_RELEASE_IMAGE="$image" \
  "$INSTALL_DIR/install.sh" prepare

