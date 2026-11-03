# API (프론트/대시보드용)

- 기본 주소: `http://<Pi Tailscale IP>:8000` (예: `http://100.80.80.16:8000`). 외부 접속은 Tailscale 경유만.
- 시각은 전부 **epoch 초(UTC)**. 표시할 때 Asia/Seoul로 변환한다.
- 갱신은 polling(10~30초 간격 권장). WebSocket/SSE는 없음.
- 다른 주소(예: `http://localhost:5173`)에서 띄우는 프론트는 서버 `.env`의 `CORS_ORIGINS`에 그 주소를 넣어야 한다(쉼표 구분).
- 오류 응답 형식: `{"detail": "..."}`. 401 = 로그인 필요/토큰 만료, 403 = 권한 없음, 422 = 잘못된 값, 503 = 저장소(InfluxDB) 장애.

## 인증

계정은 관리자가 CLI로 만든다(회원가입 API 없음). 역할: `admin`, `viewer`.

| 요청 | 설명 |
|---|---|
| `POST /api/v1/auth/login` `{"username","password"}` | → `{"access_token","refresh_token","token_type":"bearer",...}`. 5회 실패 시 15분 잠금(429) |
| `POST /api/v1/auth/refresh` `{"refresh_token"}` | 새 access/refresh 발급. refresh는 1회용(재사용 시 전체 폐기) |
| `POST /api/v1/auth/logout` `{"refresh_token"}` | refresh 폐기 |
| `GET /api/v1/auth/me` | `{"username","role"}` |

이후 모든 요청에 `Authorization: Bearer <access_token>`. access는 1시간, refresh는 14일. 401이 오면 refresh 후 재시도.

## 조회 (viewer/admin)

### `GET /api/v1/status` — 현재 상태 (메인 화면)
```json
{
  "server_time": 1793700453,
  "devices": [{
    "device_id": "freezer-01",
    "last_seen": 1793700440,
    "online": true,
    "reading": {"ts": 1793700440, "temp_c": -79.8, "door_open": false, "sensor_fault": 0},
    "alarm_level": "WARNING",
    "alarms": [{"kind": "temp", "level": "WARNING", "since": 1793700000}]
  }]
}
```
- `reading`: 가장 최근 측정 시점의 값. 측정값이 없으면 `null`. 그 시점에 센서 오류로 온도가 없으면 `temp_c: null` (옛 온도를 대신 보여주지 않음).
- `online`: 마지막 수신이 무응답 기준(`offline_after_min`, 기본 3분) 이내인지.
- `alarm_level`: `OK` | `WARNING` | `CRITICAL` (서버 판정 엔진 기준, 진행 중인 경보 중 최고 단계).
- `alarms[].kind`: `temp` | `door` | `sensor` | `offline`.
- `sensor_fault`: MAX31865 fault 비트(0x01~0x80) + 서버가 붙이는 범위 이상 비트 0x100.

### `GET /api/v1/readings?device_id=freezer-01&from=&to=` — 그래프
- `from`, `to`: epoch 초. 기본은 최근 24시간. 최대 기간 366일.
- 점이 500개를 넘지 않도록 `interval_s` 초 단위로 묶는다. `temp_c`는 구간 평균, `temp_max`는 구간 최고(평균에 묻히는 짧은 상승 확인용), `door_open`은 구간 안에서 한 번이라도 열렸으면 `true`. `ts`는 구간 시작 시각.
```json
{"device_id": "freezer-01", "from": 1793614054, "to": 1793700454, "interval_s": 173,
 "points": [{"ts": 1793614054, "temp_c": -79.9, "temp_max": -79.6, "door_open": false}]}
```
- 데이터가 없는 구간은 점이 없다(빈 칸으로 그리면 됨). 온도 없이 도어 값만 있는 점은 `temp_c: null`.

### `GET /api/v1/events?device_id=&from=&to=&active=&limit=200` — 이상 이력
- 모두 선택. `from`/`to`는 `started_at` 기준. `active=true`는 진행 중만, `false`는 해제된 것만. `limit` 최대 1000. 최근 시작 순.
```json
{"events": [{
  "id": 6, "device_id": "freezer-01", "type": "temp", "severity": "WARNING",
  "started_at": 1791260327, "resolved_at": 1791260374, "peak_value": -65.0,
  "message": "[WARNING] freezer-01 온도 -65.0℃",
  "acknowledged_by": null, "acknowledged_at": null
}]}
```
- `severity`: 그 이벤트가 도달한 최고 단계. `peak_value`: temp는 최고 온도(℃), door는 최장 열림(분), 그 외 `null`.

### `POST /api/v1/events/{id}/ack` — 이상 확인
viewer도 가능. 확인한 사람/시각을 기록하고 이벤트를 그대로 돌려준다. 이미 확인된 건은 처음 확인 기록 유지. 없는 id는 404.

### `GET /api/v1/devices` — 장치 목록
```json
{"server_time": 1793700454, "devices": [{"device_id": "freezer-01", "created_at": 1791254521, "last_seen": 1791260374, "online": false}]}
```

## 설정 (admin 전용)
- `GET /api/v1/settings` → 이상 판정 설정 전체.
- `PUT /api/v1/settings` → 보낸 항목만 변경. 예: `{"temp_warn_c": -72}`. 잘못된 값/순서 위반은 422.

## 장치 → 서버 (프론트는 사용 안 함)
- `POST /api/v1/readings` (헤더 `X-API-Key`), `GET /api/v1/time`, `GET /health`.
