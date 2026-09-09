#!/usr/bin/env sh
set -eu

ACTION="${1:-install}"
INSTALL_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$INSTALL_DIR/.env"

require_root() {
  [ "$(id -u)" -eq 0 ] || { echo "Run chronos-install as root." >&2; exit 4; }
}

get_env_from() {
  file=$1
  key=$2
  sed -n "s/^$key=//p" "$file" | tail -n 1
}

get_env() {
  get_env_from "$ENV_FILE" "$1"
}

set_env() {
  key=$1
  value=$2
  temporary="$ENV_FILE.tmp"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "$ENV_FILE" >"$temporary"
  chmod 0600 "$temporary"
  mv "$temporary" "$ENV_FILE"
}

needs_generation() {
  current=$(get_env "$1")
  [ -z "$current" ] || [ "$current" = "CHANGE_ME" ] ||
    case "$current" in replace-*) true ;; *) false ;; esac
}

random_hex() {
  openssl rand -hex "$1"
}

copy_local_kernel_bootstrap() {
  kernel_env=/opt/exocortex/kernel/.env
  [ -r "$kernel_env" ] || return 0
  current_url=$(get_env KERNEL_URL)
  current_token=$(get_env KERNEL_SERVICE_TOKEN)
  case "$current_url" in ""|CHANGE_ME|*CHANGE_ME*)
    local_url=$(get_env_from "$kernel_env" KERNEL_URL)
    [ -n "$local_url" ] && set_env KERNEL_URL "$local_url"
  ;; esac
  case "$current_token" in ""|CHANGE_ME|*CHANGE_ME*)
    local_token=$(get_env_from "$kernel_env" KERNEL_SERVICE_TOKEN)
    [ -n "$local_token" ] && set_env KERNEL_SERVICE_TOKEN "$local_token"
  ;; esac
}

install_command() {
  install -d -m 0755 /usr/local/sbin
  wrapper=/usr/local/sbin/chronos-install
  {
    echo '#!/usr/bin/env sh'
    printf 'exec "%s/install.sh" "$@"\n' "$INSTALL_DIR"
  } >"$wrapper"
  chmod 0755 "$wrapper"
}

prepare_neptune_mounts() {
  getent group neptune-clients >/dev/null 2>&1 || groupadd --system neptune-clients
  neptune_gid=$(getent group neptune-clients | cut -d: -f3)
  install -d -o root -g neptune-clients -m 0770 /run/neptune
  install -d -o root -g neptune-clients -m 0750 /etc/neptune/clients
  control_file=/etc/neptune/clients/chronos.control.token
  export_file=/etc/neptune/clients/chronos.export.token
  for token_file in "$control_file" "$export_file"; do
    if [ ! -s "$token_file" ]; then
      umask 0027
      random_hex 32 >"$token_file"
    fi
    chown root:neptune-clients "$token_file"
    chmod 0640 "$token_file"
  done
  set_env NEPTUNE_SOCKET_GID "$neptune_gid"
  set_env NEPTUNE_CONTROL_TOKEN_HOST_FILE "$control_file"
  set_env NEPTUNE_EXPORT_TOKEN_HOST_FILE "$export_file"
}

prepare_gryphon_mounts() {
  getent group gryphon-clients >/dev/null 2>&1 || groupadd --system gryphon-clients
  gryphon_gid=$(getent group gryphon-clients | cut -d: -f3)
  install -d -o root -g gryphon-clients -m 0770 /run/gryphon
  install -d -o root -g gryphon-clients -m 0750 /etc/gryphon/clients
  token_file=/etc/gryphon/clients/chronos.token
  if [ ! -s "$token_file" ]; then
    umask 0027
    random_hex 32 >"$token_file"
  fi
  chown root:gryphon-clients "$token_file"
  chmod 0640 "$token_file"
  set_env GRYPHON_CLIENTS_GID "$gryphon_gid"
  set_env GRYPHON_SERVICE_TOKEN_HOST_FILE "$token_file"
}

enable_backup() {
  require_root
  [ -f "$ENV_FILE" ] || { echo "Install Chronos first." >&2; exit 2; }
  command -v updater >/dev/null 2>&1 || { echo "Updater is required." >&2; exit 3; }
  prepare_neptune_mounts
  updater neptune install --head chronos
  enrollment_code=${NEPTUNE_ENROLLMENT_CODE:-}
  if [ -z "$enrollment_code" ]; then
    printf 'Saturn one-time setup code: ' >&2
    stty -echo; trap 'stty echo' EXIT HUP INT TERM; IFS= read -r enrollment_code; stty echo; trap - EXIT HUP INT TERM; printf '\n' >&2
  fi
  printf '%s\n' "$enrollment_code" | updater neptune enroll --head chronos --project chronos --export-url "http://127.0.0.1:$(get_env CHRONOS_LISTEN_PORT)/api/internal/neptune/backup"
  unset enrollment_code
  echo "Chronos automatic backup is connected. Enable its schedule in Settings."
}

prepare() {
  require_root
  command -v openssl >/dev/null 2>&1 || {
    echo "openssl is required. Prepare the VPS with Sindri first." >&2
    exit 3
  }
  [ -f "$ENV_FILE" ] || cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  needs_generation CHRONOS_SESSION_SECRET && set_env CHRONOS_SESSION_SECRET "$(random_hex 32)"
  needs_generation CHRONOS_DB_PASSWORD && set_env CHRONOS_DB_PASSWORD "$(random_hex 32)"
  needs_generation UPDATER_CONTROL_TOKEN && set_env UPDATER_CONTROL_TOKEN "$(random_hex 32)"
  set_env UPDATER_COMPOSE_PROJECT_DIR "$INSTALL_DIR"
  [ -z "${CHRONOS_RELEASE_VERSION:-}" ] || set_env CHRONOS_VERSION "$CHRONOS_RELEASE_VERSION"
  [ -z "${CHRONOS_RELEASE_IMAGE:-}" ] || set_env CHRONOS_IMAGE "$CHRONOS_RELEASE_IMAGE"
  copy_local_kernel_bootstrap
  prepare_neptune_mounts
  prepare_gryphon_mounts
  install_command
  echo "Chronos files are prepared in $INSTALL_DIR"
  echo "Edit only the OPERATOR INPUT section in $ENV_FILE"
  echo "Then run: sudo chronos-install"
}

validate_install() {
  [ -f "$ENV_FILE" ] || { echo "Run the Chronos bootstrap command first." >&2; exit 2; }
  for command in docker curl openssl; do
    command -v "$command" >/dev/null 2>&1 || {
      echo "$command is required. Prepare the VPS with Sindri first." >&2
      exit 3
    }
  done
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 3; }
  access_key=$(get_env CHRONOS_ACCESS_KEY)
  kernel_url=$(get_env KERNEL_URL)
  kernel_token=$(get_env KERNEL_SERVICE_TOKEN)
  image=$(get_env CHRONOS_IMAGE)
  case "$access_key" in ""|CHANGE_ME|change-*) echo "Set CHRONOS_ACCESS_KEY in .env." >&2; exit 2 ;; esac
  [ "${#access_key}" -ge 12 ] || { echo "CHRONOS_ACCESS_KEY must contain at least 12 characters." >&2; exit 2; }
  case "$kernel_url" in https://*.*) ;; *) echo "KERNEL_URL must be the public HTTPS Kernel URL." >&2; exit 2 ;; esac
  case "$kernel_url" in *CHANGE_ME*|*.example.com*) echo "Replace the example KERNEL_URL." >&2; exit 2 ;; esac
  [ "${#kernel_token}" -ge 24 ] || { echo "Copy KERNEL_SERVICE_TOKEN from Kernel into .env." >&2; exit 2; }
  printf '%s' "$image" | grep -Eq '^ghcr\.io/.+@sha256:[a-f0-9]{64}$' || {
    echo "CHRONOS_IMAGE was not populated from a valid release." >&2
    exit 2
  }
  docker pull "$image" >/dev/null || {
    echo "Cannot pull the Chronos image. Make the GHCR package public or authenticate Docker to ghcr.io." >&2
    exit 14
  }
  set_env UPDATER_PUBLIC_HEALTH_URL ""
}

install_chronos() {
  require_root
  validate_install
  prepare_neptune_mounts
  prepare_gryphon_mounts
  docker network inspect exocortex-services >/dev/null 2>&1 || docker network create exocortex-services >/dev/null
  cd "$INSTALL_DIR"
  "$INSTALL_DIR/updater/install.sh" chronos "$ENV_FILE" "$INSTALL_DIR/updater/updater-linux-amd64"
  docker compose --env-file "$ENV_FILE" -f compose.production.yaml config -q
  docker compose --env-file "$ENV_FILE" -f compose.production.yaml up -d
  port=$(get_env CHRONOS_LISTEN_PORT)
  port=${port:-18280}
  for _ in $(seq 1 45); do
    if curl -fsS --max-time 3 "http://127.0.0.1:$port/api/health" >/dev/null; then
      echo "Chronos is healthy on 127.0.0.1:$port"
      echo "Configure the public domain, certificate and Nginx separately through Sindri."
      return 0
    fi
    sleep 2
  done
  docker compose --env-file "$ENV_FILE" -f compose.production.yaml ps >&2
  docker compose --env-file "$ENV_FILE" -f compose.production.yaml logs --tail=100 chronos >&2
  echo "Chronos did not become healthy within 90 seconds." >&2
  exit 15
}

case "$ACTION" in
  prepare) prepare ;;
  install) install_chronos ;;
  status)
    require_root
    cd "$INSTALL_DIR"
    docker compose --env-file "$ENV_FILE" -f compose.production.yaml ps
  ;;
  backup) enable_backup ;;
  *) echo "Usage: chronos-install [install|prepare|status|backup]" >&2; exit 2 ;;
esac
