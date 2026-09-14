#!/usr/bin/env bash
set -euo pipefail

version="${1:?version is required}"
output="${2:-release-artifacts}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
case "$output" in /*) ;; *) output="$root/$output" ;; esac
repository="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
image_reference="${IMAGE_REFERENCE:?IMAGE_REFERENCE is required}"
image_digest="${IMAGE_DIGEST:?IMAGE_DIGEST is required}"
updater_dir="${UPDATER_BUNDLE_DIR:?UPDATER_BUNDLE_DIR is required}"
updater_version="${UPDATER_BUNDLE_VERSION:?UPDATER_BUNDLE_VERSION is required}"
[[ "$updater_version" == "$(tr -d '[:space:]' < "$root/.release/updater.version")" ]] || { echo 'Updater pin mismatch' >&2; exit 6; }

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || exit 2
[[ -f "$updater_dir/install.sh" && -f "$updater_dir/updater-linux-amd64" ]] || {
  echo "Verified Updater install bundle is incomplete" >&2
  exit 3
}

mkdir -p "$output"
public_key="${RELEASE_PUBLIC_KEY_FILE:-$output/chronos.pem}"
[[ -f "$public_key" ]] || { echo 'Export the release public key before building' >&2; exit 6; }
for scope in updater neptune gryphon; do
  [[ -f "$updater_dir/release-trust/$scope.pem" ]] || { echo "Missing signed Updater trust scope $scope" >&2; exit 6; }
done
[[ "$version" == "$(node -p "require('./web/package.json').version")" ]] || { echo 'Source/release version mismatch' >&2; exit 6; }
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp "$root/compose.yaml" "$root/compose.production.yaml" "$root/compose.updater.yaml" \
  "$root/.env.example" "$root/install.sh" "$root/bootstrap.sh" \
  "$root/nginx.security.conf" "$root/README.md" "$root/DEPLOYMENT.md" "$root/nginx.server.example.conf" "$stage/"
cp -R "$updater_dir" "$stage/updater"
find "$stage/updater" -type f -name '*.sh' -exec chmod 0755 {} +
chmod 0755 "$stage/install.sh" "$stage/bootstrap.sh" "$stage/updater/updater-linux-amd64"
sed -i \
  -e "s|^CHRONOS_VERSION=.*|CHRONOS_VERSION=$version|" \
  -e "s|^CHRONOS_IMAGE=.*|CHRONOS_IMAGE=${image_reference}@${image_digest}|" \
  "$stage/.env.example"

bundle="$output/chronos-${version}-compose.tar.gz"
tar -czf "$bundle" -C "$stage" .
bundle_sha="$(sha256sum "$bundle" | awk '{print $1}')"
cat > "$output/chronos-release.json" <<EOF
{
  "schema_version": 1,
  "service": "chronos",
  "version": "$version",
  "channel": "stable",
  "image": {
    "reference": "$image_reference",
    "digest": "$image_digest"
  },
  "compose_bundle": {
    "url": "https://github.com/${repository}/releases/download/chronos-v${version}/chronos-${version}-compose.tar.gz",
    "sha256": "$bundle_sha"
  },
  "minimum_updater_version": "$updater_version",
  "database_schema": 10,
  "backup_schema": "exocortex.chronos.backup.v1",
  "compose_contract": 2,
  "release_notes_url": "https://github.com/${repository}/releases/tag/chronos-v${version}"
}
EOF

node "$root/scripts/build-bootstrap.mjs" "$root/bootstrap.sh" "$public_key" "$output/bootstrap.sh" "$version"
