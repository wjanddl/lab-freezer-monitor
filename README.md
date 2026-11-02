# 연구실 -80℃ 냉동고 모니터링

구조/원칙은 [CLAUDE.md](CLAUDE.md) 참고.

## 로컬 실행 (Windows, Docker Desktop)

```
copy .env.example .env      # 비밀번호/토큰 값을 반드시 변경
docker compose up -d --build
curl http://localhost:8000/health
```
기대 출력: `{"status":"ok","influx":true}` (Influx 기동에 최대 ~30초)

테스트: `docker compose run --rm api pytest -q`

## 라즈베리파이 배포 (초안)

Raspberry Pi OS 64bit + Docker 설치 후 위와 동일하게 `docker compose up -d --build`.
이미지는 모두 arm64 지원. 재부팅/정전 후 `restart: unless-stopped`로 자동 기동.

> **보안 전제:** api는 `0.0.0.0:8000`에 바인딩된다. 외부(학교망) 노출은 반드시
> 방화벽(nftables)과 Tailscale로 막는다. 포트포워딩 금지. (8단계에서 스크립트 제공)
