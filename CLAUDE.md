# 프로젝트: 연구실 -80℃ 초저온냉동고 실시간 모니터링 (백엔드 + 펌웨어 + Pi 운영)

## 목적
-80℃ 냉동고의 고장/정전으로 인한 샘플 손실을 막기 위해 온도와 도어 상태를 실시간 수집하고,
이상 시 카카오톡으로 즉시 알림한다. 프론트(대시보드)는 팀원이 별도 개발하며 이 백엔드 API를 사용한다.

## 아키텍처 (확정, 임의 변경 금지)
- 센서: PT100 백금 RTD + MAX31865(SPI), 유선 마그네틱 리드스위치(GPIO)
- ESP32 NodeMCU → Wi-Fi(Pi가 만든 사설 AP, WPA2-PSK) → HTTP POST(JSON) → Pi의 FastAPI
- Pi: wlan0 = AP(192.168.50.0/24, Pi=192.168.50.1), eth0 = 연구실 유선 LAN(DHCP, 외부로 나가기만 함)
- AP 클라이언트(ESP32)는 Pi의 API 포트만 접근 가능. AP → eth0 포워딩은 차단(기본 차단).
- 대시보드/API 외부 접속은 Tailscale 경유만. 공인 IP 노출/포트포워딩 금지.
- 저장: InfluxDB 2.x(시계열), SQLite(설정, 사용자, 이상이력, 알림상태)
- 알림: 텔레그램 봇(확정, 단체방으로 여러 명 수신), 폴백은 이메일, 별도 생존신호: healthchecks.io로 주기적 ping
- 외부 접속: Tailscale 무료 플랜 범위 안에서만 사용 (소수의 관리자/프론트 담당만 접속, 나머지 팀원은 봇 알림 수신)

## 기술 스택
- 서버: Python 3.11+, FastAPI, Uvicorn, Pydantic v2, httpx, pytest, Docker Compose(arm64 호환)
- 펌웨어: Arduino 프레임워크 + PlatformIO, esp32dev, Adafruit_MAX31865
- 개발은 사용자 PC(Windows)에서, 실행/배포는 라즈베리파이(Raspberry Pi OS 64bit)

## 디렉터리 구조
/server    FastAPI 앱 (app/, tests/, Dockerfile)
/firmware  PlatformIO 프로젝트 (src/, include/config.example.h)
/pi-setup  Pi 네트워크/운영 스크립트 (AP, 방화벽, Tailscale, 백업)  ← Claude Code는 Pi에서 실행 검증 불가
/tools     센서 없이 테스트하는 시뮬레이터
/docs      API.md, NETWORK.md, WIRING.md, OPERATIONS.md
docker-compose.yml, .env.example, README.md

## 작업 원칙 (중요)
1. 확실하지 않은 사항은 임의로 정하지 말고 나에게 먼저 질문한다. 질문은 한 번에 모아서 한다.
2. 복잡한 설계/결정은 단계별로 근거를 설명한 뒤 진행한다.
3. 각 단계가 끝나면 만든 것, 실행/검증 방법을 요약하고 내 확인을 받은 뒤 다음 단계로 간다.
4. 임계값, 시간, 주기, 핀 번호 등 하드웨어/운영 의존 값은 하드코딩하지 말고 설정으로 분리한다.
5. 비밀값(API 키, 카카오 토큰, AP 비밀번호, JWT 시크릿, healthchecks URL)은 절대 커밋하지 않는다.
6. 안전 우선(fail-safe): "데이터가 안 오는 것"도 이상 상황으로 취급한다.
7. 시간은 UTC로 저장하고 표시용 변환만 Asia/Seoul.
8. Pi에서 직접 실행해야 하는 시스템 설정(네트워크/방화벽/Tailscale)은 스크립트를 짜더라도
   "검증하지 못했다"고 명시하고, 사용자가 Pi에서 따라 할 단계별 확인 절차(기대 출력 포함)를 문서로 남긴다.
   OS 버전(NetworkManager인지 dhcpcd인지)에 따라 명령이 다르므로 추측하지 말고 먼저 `cat /etc/os-release`와
   `nmcli -v` 결과를 내게 요청한다.
9. 코드 주석과 문서는 한국어, 식별자는 영어.

## 진행 상태 (2026-10-06 기준)
- 완료: 1단계(골격/인프라), 2단계(수신 API), 3단계(이상 판정 엔진, settings API), 4단계(텔레그램 알림), 5단계(인증/JWT), 6단계(조회 API), 9단계(시뮬레이터/E2E) — pytest 65개 + E2E 22개 통과
- 5단계: 계정은 CLI로만 생성(`docker compose run --rm api python -m app.cli create-user --username X --role admin|viewer`, 비밀번호는 프롬프트).
  역할 admin/viewer, access 1시간 + refresh 14일(회전, 재사용 시 전체 폐기), 로그인 5회 실패 시 15분 잠금(429). 엔드포인트: /api/v1/auth/{login,refresh,logout,me}. settings API는 admin 전용
- .env 편집 주의: PowerShell 5.1의 Get-Content/Set-Content는 UTF-8 한글을 깨뜨리고 BOM을 붙임 → 메모장(UTF-8) 또는 [IO.File]::WriteAllLines + UTF8Encoding($false) 사용
- 4단계: 실제 단체방 수신 확인(WARNING/복구). 발송 실패 시 즉시 재시도 2회 + 다음 틱 재시도. 이메일 폴백(SMTP)은 보류(필요 시 추가)
- 6단계: 조회 API(/status, /readings, /events, /events/{id}/ack, /devices), docs/API.md. 모두 로그인 필요(viewer 가능), CORS는 CORS_ORIGINS
- Pi(100.80.80.16, Tailscale) 배포 완료: ~/freezer-monitor에서 docker compose. OLED는 ~/freezer-oled/live_display.py(viewer 계정 oled, 서비스 등록 전)
- 생존신호: HEALTHCHECK_URL에 60초마다 ping(틱+Influx 정상), 아니면 /fail. Pi .env에는 아직 비어 있음(사용자가 healthchecks.io에서 생성 필요)
- 9단계: tools/simulate.py(측정값 전송 CLI), E2E는 `powershell -File tools/e2e/run.ps1` (별도 프로젝트 freezer-e2e, 가짜 텔레그램, 끝나면 볼륨 삭제. 운영 데이터/단체방 영향 없음)
- 다음: 7(펌웨어)·8(Pi 운영)은 하드웨어 도착 후.
- 개발 편의: tools/send.ps1 (`$key` 설정 후 `. .\tools\send.ps1; Send -79.8`)로 측정값 전송 테스트
- 검증 방법: `docker compose run --rm api pytest -q`, README 참고

## 확정된 결정 (진행 중 누적)
- 작업 순서: 1단계 직후 Pi AP + ESP32 접속 최소 스케치를 먼저 검증하고 2~6단계로 진행
- PT100 결선/RREF: 모듈 도착 전까지 기본값(3선, 430Ω)을 config로 분리
- 알림톡/문자(SMS)는 대행사 가입 부담으로 폐기 → 메신저 봇으로 변경 (카카오톡 봇은 일반 발송 불가라 후보에서 제외), 폴백 채널은 이메일
- 수신 대상(웹훅 URL/채팅 ID)은 비밀값이므로 .env에 두고 설정 DB에는 넣지 않음
- 하드웨어(ESP32, Pi)는 아직 없음 → 서버 2~6단계와 시뮬레이터(9단계)를 먼저 진행, 7·8단계는 하드웨어 도착 후
- 범위 밖 temp_c는 거부하지 않고 저장하되 temp_c 필드는 버리고 sensor_fault에 0x100 비트를 추가
- Tailscale은 무료 플랜 수준으로만 (제한은 8단계에서 최신 문서 확인 후 접속 대상 조정)
- Pi 사양/OS 미정 (8단계 전에 확인 필요)
- (2026-11-03) 센서 연결 전 임시: Pi 설정 DB의 remind_crit_min을 30→1440(하루 1회)으로 변경. 남아 있는 freezer-01 무응답 CRITICAL 재알림 폭주 방지. **센서 연결 시 PUT /api/v1/settings {"remind_crit_min": 30}으로 되돌릴 것**
