# 가정 기기 런북 (Raspberry Pi)

이 문서는 어르신 댁에 기기 한 대를 놓고 4주 동안 운영하는 절차다. 설치하는 사람이 위에서부터 그대로 따라 한다.

## 집 밖으로 나가는 것

- 집 밖으로 나가는 것은 알림 문장, 창별 합계 두 숫자(평소·실제), 하루 리듬 요약(시간대별 사용 여부 24칸)뿐이다. 원시 측정값·시간별 값·영상·음성은 집 밖에 없다.
- 알림 행에는 **알림 문장**("이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다")과 센서별 이유·6시간 창 합계 두 숫자(평소·실제)가, 일일 요약 행에는 한 줄 문장과 센서별 참/거짓 24칸·첫 사용 시각이 들어간다. Supabase(가족 앱)로만 가고, 선택한 Apprise 채널에는 알림 문장만 간다.
- 수도·전력 원시 값, 시간별 사용량, 학습한 통계는 기기의 `/var/lib/solowatch/home.sqlite` 에만 남는다.
- 카메라·마이크는 쓰지 않는다. 기기는 신고 기관에 연락하지 않는다. 알림을 받은 가족이 전화하고 판단한다.
- 브로커(Mosquitto)는 집 안 네트워크에서만 쓴다. 공유기에서 포트를 열지 않는다.

## 준비물

| 항목 | 수량 | 비고 |
|---|---|---|
| Raspberry Pi 4 또는 5 (RAM 2 GB 이상) | 1 | 전원 어댑터, microSD 32 GB |
| 전력 측정 스마트플러그 (Tasmota 펌웨어 또는 Zigbee) | 3 | 냉장고·TV·거실등 |
| Zigbee USB 동글 | 0~1 | Zigbee 플러그를 쓸 때만 (Zigbee2MQTT) |
| 펄스 출력 수도 유량 센서 + ESP32/ESP8266 (ESPHome 또는 Tasmota) | 1 | 수도 계량기 뒤 본관. 배관 작업은 자격자가 한다 |

## 설치

1. **OS 굽기.** Raspberry Pi Imager 로 *Raspberry Pi OS Lite (64-bit)* 를 굽는다. 고급 설정에서 호스트명 `solowatch`, 사용자, Wi-Fi, SSH 를 켠다.
2. **접속.** 같은 네트워크에서 `ssh <사용자>@solowatch.local`.
3. **코드 받기.**
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone <저장소 URL> ~/solowatch
   ```
4. **설치 스크립트 실행.** 여러 번 실행해도 된다 (멱등).
   ```bash
   sudo bash ~/solowatch/deploy/install.sh
   ```
   스크립트가 하는 일:
   - `apt` 로 `mosquitto`·`mosquitto-clients`·`rsync` 설치, 없으면 `uv` 설치 (`/usr/local/bin`)
   - 시스템 사용자 `solowatch`, `/var/lib/solowatch`(데이터), `/etc/solowatch`(설정) 생성
   - 코드를 `/opt/solowatch` 로 복사하고 `uv sync --no-dev --frozen`
   - `deploy/mosquitto.conf` → `/etc/mosquitto/conf.d/solowatch.conf`. 브로커 사용자 `solowatch` 가 없으면 만들고 비밀번호를 `/etc/solowatch/mqtt-password` 에 둔다
   - `/etc/solowatch/solowatch.toml`, `/etc/solowatch/solowatch.env` 가 없을 때만 예시에서 만든다 (있으면 건드리지 않는다)
   - `solowatch.service` 를 `enable` 하고 시작, 상태 출력
5. **비밀 값 채우기.** `sudo nano /etc/solowatch/solowatch.env` — `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SOLOWATCH_DEVICE_EMAIL`, `SOLOWATCH_DEVICE_PASSWORD`, 선택 `SOLOWATCH_APPRISE_URLS`. 형식은 `deploy/solowatch.env.example`.
6. **기기 사용자 만들기 (Supabase).** 가족 앱과 같은 Supabase 프로젝트의 Authentication 에서 기기 전용 이메일 사용자를 만들고, `household_members` 에 그 사용자를 해당 가구의 `device` 역할로 넣는다. 기기는 이 계정으로 알림·일일 요약을 쓰고 가족 판단·외출 기간을 읽기만 한다.
7. **재시작.** `sudo systemctl restart solowatch`. 설정·env 가 빠져 있으면 데몬은 exit 2 로 멈추고(재시작하지 않음) 로그에 빠진 이름을 남긴다.

## 센서 연결

모든 센서는 집 안 브로커 `solowatch.local:1883` 에 사용자 `solowatch` / `/etc/solowatch/mqtt-password` 로 접속한다.

| 장치 | 설정 위치 | 토픽 예 | `solowatch.toml` 의 `[[sensor]]` |
|---|---|---|---|
| Tasmota 플러그 | 웹 UI → Configuration → MQTT (Host `solowatch.local`, Topic `tv`), Telemetry period 60 | `tele/tv/SENSOR` | `topic = "tele/tv/SENSOR"`, `value_path = "ENERGY.Power"`, `ts_path = "Time"` |
| Zigbee 플러그 | Zigbee2MQTT `configuration.yaml` 의 `mqtt.server: mqtt://solowatch.local` | `zigbee2mqtt/living_light` | `topic = "zigbee2mqtt/living_light"`, `value_path = "power"` |
| Home Assistant 경유 | MQTT 통합 + 자동화로 센서 값을 위 형식으로 publish | `solowatch/home-demo/plug_fridge/state` | `topic` 만 맞추면 기본 `value_path = "value"` |
| 수도 유량 (ESP) | ESPHome `pulse_counter` 를 리터로 환산해 MQTT publish | `solowatch/home-demo/water_main/state` | `{"ts": "...", "value": 리터}` 기본 형식 |

`/etc/solowatch/solowatch.toml` 에서:

- `[household]` 의 `id`·`slug`·`name` 을 가족 앱 가구와 맞춘다. `install_start` 는 설치한 날 (학습 시작일).
- 센서 4개(`water_main`, `plug_fridge`, `plug_tv`, `plug_light`)의 `topic`·`value_path` 를 위 표대로 고친다. `min_deviation`·`active_threshold` 는 예시 값 그대로 둔다.
- `[mqtt]` 는 설치 스크립트가 `host = "localhost"`, `port = 1883`, 사용자·비밀번호를 채웠다.

고친 뒤 `sudo systemctl restart solowatch`.

## 검증

```bash
systemctl status solowatch mosquitto          # 둘 다 active (running)
journalctl -u solowatch -n 50 --no-pager      # 연결·수집 로그, 오류 없음
journalctl -u solowatch -f                    # 실시간
mosquitto_sub -h localhost -u solowatch -P "$(sudo cat /etc/solowatch/mqtt-password)" -t '#' -v -C 5
sudo -u solowatch sqlite3 /var/lib/solowatch/home.sqlite \
  "SELECT sensor_id, COUNT(*), MAX(ts) FROM readings GROUP BY sensor_id;"   # 센서 4개, 최근 시각
```

- `mosquitto_sub` 에 네 센서의 메시지가 보이면 장치 연결은 끝이다.
- `readings` 에 네 센서가 모두 쌓이면 수집이 된다. 하나가 없으면 그 센서의 `topic`·`value_path` 를 다시 본다.
- 저녁 `daily_report_hour`(기본 20시)가 지나면 가족 앱에 그날 요약 한 줄이 보인다.
- 재부팅 후에도 두 서비스가 자동으로 올라오는지 `sudo reboot` 뒤 다시 확인한다.
- Debian 기본 `/etc/mosquitto/mosquitto.conf` 에도 `persistence` 설정이 있으면 `conf.d/solowatch.conf` 와 중복 오류가 날 수 있다. `sudo mosquitto -c /etc/mosquitto/mosquitto.conf -v` 로 한 번 띄워 오류 메시지가 없는지 확인한다 (실 Pi 미검증 항목).

## 4주 운영

| 기간 | 기기 | 가족 |
|---|---|---|
| 1~2주차 (학습) | 평일·주말 × 하루 4개 시간 창의 평소 사용량을 배운다. 알림 없음, 일일 요약만 | 앱에서 요약이 매일 오는지만 본다 |
| 3~4주차 (알림) | 평소와 다르면 "이상 가능성 있음" 알림 | 알림마다 전화로 확인하고 앱에 판단을 남긴다 |

가족이 남기는 기록:

- **괜찮았음** — 알림이 왔지만 실제로는 괜찮았다 (예: 친구 집에서 자고 옴). 오경보로 집계되고, 기기는 그 값을 평소 범위로 배운다.
- **실제 이상** — 알림이 왔고 실제로 평소와 달랐다.
- **놓친 경보** — 알림이 없었는데 이상이 있었다 (예: 감기로 종일 누움). 앱에서 그 날짜를 골라 남긴다.
- **외출·여행** — 미리 앱에 기간을 표시한다. 그 기간에는 알림을 쉬고 학습에도 쓰지 않는다.

4주가 끝나면 기기에서 운영 기록 표를 만든다:

```bash
sudo -u solowatch /opt/solowatch/.venv/bin/python -m solowatch.ops_report \
  --db /var/lib/solowatch/home.sqlite --out /var/lib/solowatch/ops-report.md \
  --json /var/lib/solowatch/ops-report.json
```

표는 `날짜 | 알림 | 가족 판단 | 분류` 와 `합계 | 알림 N건 | | 오경보 n건 · 놓친 경보 m건` 줄이다. 모의 데이터로 만든 예시는 `docs/ops-sample.md` (`scripts/make_ops_sample.sh` 로 재생성).

## 문제 해결

| 증상 | 확인 |
|---|---|
| `solowatch` 가 `inactive (dead)`, exit 2 | `journalctl -u solowatch` 의 누락 이름을 `solowatch.env` 또는 `solowatch.toml` 에 채우고 restart |
| 계속 재시작 (exit 3) | 브로커 연결 실패. `systemctl status mosquitto`, `[mqtt]` 사용자·비밀번호 |
| 센서 하나만 비어 있음 | `mosquitto_sub -t '#' -v` 로 실제 토픽 확인 후 `topic`·`value_path` 수정 |
| 가족 앱에 알림이 안 보임 | 기기 사용자의 `device` 멤버십, `SUPABASE_URL`·키. 미전송 알림은 다음 주기에 다시 보낸다 |
