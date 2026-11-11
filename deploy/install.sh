#!/usr/bin/env bash
# 홀로안심 가정 기기(Raspberry Pi OS Lite 64-bit) 설치. 여러 번 실행해도 결과가 같다 (멱등).
#   sudo bash deploy/install.sh
# 하는 일: mosquitto·uv 설치 → solowatch 사용자·디렉터리 → /opt/solowatch 복사 → uv sync --no-dev
#          → 브로커 설정 → /etc/solowatch 설정 파일(없을 때만) → systemd 유닛 enable·start → 상태 출력.
# 집 밖으로 나가는 데이터는 알림 문장과 일일 요약뿐이다. 센서 원시 값은 /var/lib/solowatch 에만 남는다.
set -euo pipefail

APP_USER=solowatch
APP_DIR=/opt/solowatch
DATA_DIR=/var/lib/solowatch
CONF_DIR=/etc/solowatch
CONF_FILE="$CONF_DIR/solowatch.toml"
ENV_FILE="$CONF_DIR/solowatch.env"
MQTT_PASSWD=/etc/mosquitto/passwd
MQTT_SECRET="$CONF_DIR/mqtt-password"
UNIT=/etc/systemd/system/solowatch.service
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '[install] %s\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "root 권한이 필요하다: sudo bash $0" >&2
  exit 1
fi

# 1. 패키지 (apt) — 없을 때만 설치
missing=()
for pkg in mosquitto mosquitto-clients rsync curl ca-certificates; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  log "apt install ${missing[*]}"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
fi

# 2. uv (공식 설치 스크립트, /usr/local/bin) — 없을 때만
if ! command -v uv >/dev/null 2>&1; then
  log "install uv -> /usr/local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
UV="$(command -v uv)"

# 3. 서비스 사용자·디렉터리
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  log "create system user $APP_USER"
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o root -g root -m 755 "$APP_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR"
install -d -o root -g "$APP_USER" -m 750 "$CONF_DIR"

# 4. 프로젝트 복사 (가상환경·파이썬은 보존, 개발 산출물은 제외)
log "sync $SRC_DIR -> $APP_DIR"
rsync -a --delete \
  --exclude '.git/' --exclude '.ai/' --exclude '.venv/' --exclude '.python/' \
  --exclude 'web/' --exclude 'data/' --exclude 'supabase/' --exclude 'tests/' \
  --exclude '.env' --exclude '__pycache__/' --exclude '*.sqlite' \
  "$SRC_DIR/" "$APP_DIR/"

# 5. 런타임 의존성. 파이썬도 /opt/solowatch 아래에 받아 solowatch 사용자가 읽을 수 있게 한다.
log "uv sync --no-dev"
(
  cd "$APP_DIR"
  UV_PYTHON_INSTALL_DIR="$APP_DIR/.python" UV_PROJECT_ENVIRONMENT="$APP_DIR/.venv" \
    "$UV" sync --no-dev --frozen
)

# 6. 브로커 설정 (LAN 안 1883, 익명 금지)
install -m 644 "$SRC_DIR/deploy/mosquitto.conf" /etc/mosquitto/conf.d/solowatch.conf
mqtt_password=""
if [[ ! -f "$MQTT_PASSWD" ]]; then
  log "create broker user $APP_USER (password -> $MQTT_SECRET)"
  mqtt_password="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  mosquitto_passwd -c -b "$MQTT_PASSWD" "$APP_USER" "$mqtt_password"
  umask 077
  printf '%s\n' "$mqtt_password" > "$MQTT_SECRET"
  umask 022
fi
chown mosquitto:mosquitto "$MQTT_PASSWD"
chmod 600 "$MQTT_PASSWD"

# 7. 설정 파일 — 없을 때만 예시에서 만든다 (이미 있으면 건드리지 않는다)
if [[ ! -f "$CONF_FILE" ]]; then
  log "create $CONF_FILE from example"
  sed -e 's|^port = .*|port = 1883|' \
      -e "s|^path = .*|path = \"$DATA_DIR/home.sqlite\"|" \
      -e "s|^username = .*|username = \"$APP_USER\"|" \
      -e "s|^password = .*|password = \"$mqtt_password\"|" \
      "$SRC_DIR/config/solowatch.example.toml" > "$CONF_FILE"
  if [[ -z "$mqtt_password" ]]; then
    log "WARN: 기존 $MQTT_PASSWD 를 썼다. $CONF_FILE 의 [mqtt] password 를 직접 채운다."
  fi
fi
if [[ ! -f "$ENV_FILE" ]]; then
  log "create $ENV_FILE from example (값을 채운 뒤 systemctl restart solowatch)"
  install -m 640 "$SRC_DIR/deploy/solowatch.env.example" "$ENV_FILE"
fi
chown root:"$APP_USER" "$CONF_FILE" "$ENV_FILE"
chmod 640 "$CONF_FILE" "$ENV_FILE"

# 8. systemd
install -m 644 "$SRC_DIR/deploy/solowatch.service" "$UNIT"
systemctl daemon-reload
systemctl enable mosquitto.service
systemctl restart mosquitto.service
systemctl enable solowatch.service
systemctl restart solowatch.service

# 9. 상태
sleep 2
systemctl --no-pager --lines=20 status mosquitto.service solowatch.service || true
log "done. 로그: journalctl -u solowatch -f"
