#!/usr/bin/env bash
# README 30초 데모 GIF 재생성: 데모 서버(8845) → Playwright record 프로젝트 녹화(webm) → ffmpeg → docs/figures/demo-30s.gif.
# 전제: supabase start, .env · web/.env.local 채움, ffmpeg 설치.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT=8845
WEBM="web/test-results/record/demo.webm"
GIF="docs/figures/demo-30s.gif"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if lsof -ti "tcp:$PORT" >/dev/null 2>&1; then
  echo "port $PORT is busy; stop the process using it first" >&2
  exit 1
fi

stop_server() { lsof -ti "tcp:$PORT" | xargs kill 2>/dev/null || true; }
trap stop_server EXIT

uv run solowatch demo-server --port "$PORT" &

wait_ready() {
  for _ in $(seq 1 60); do
    if curl -sf "http://localhost:$PORT/healthz" 2>/dev/null | grep -q '"ready": *true'; then
      return 0
    fi
    sleep 1
  done
  echo "demo server not ready within 60s" >&2
  return 1
}
wait_ready
# 녹화를 결정적으로: 공유 가구를 처음 상태(day_index 0)로 되돌린다
curl -sf -X POST "http://localhost:$PORT/api/demo/reset" >/dev/null
wait_ready

rm -f "$WEBM"
(cd web && npx playwright test --project=record)
test -s "$WEBM"

mkdir -p "$(dirname "$GIF")"
ffmpeg -y -i "$WEBM" -t 35 \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
  "$GIF"
echo "GIF $ROOT/$GIF"
