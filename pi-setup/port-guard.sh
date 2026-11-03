#!/bin/sh
# Docker로 공개한 API 포트를 외부망 인터페이스에서 차단 (Tailscale·localhost만 접근).
# Docker 공개 포트는 ufw/INPUT 규칙을 우회하므로 Docker가 제공하는 DOCKER-USER 체인에 넣는다.
# 재부팅/도커 재시작 때마다 freezer-port-guard.service가 다시 실행 (중복 추가 안 함).
# 8단계에서 wlan0을 ESP32용 AP로 바꾸면 IFACES에서 wlan0을 빼고 AP 대역만 허용하도록 수정할 것.
# ⚠ 검증: 2026-11-03 Pi(bookworm, docker 29.9.2)용으로 작성. 실제 적용 결과는 docs/OPERATIONS.md 절차로 확인.
set -eu
IFACES="${IFACES:-wlan0 eth0}"   # 차단할 외부망 인터페이스 (현재 wlan0 = 학교 Wi-Fi 클라이언트)
PORTS="${PORTS:-8000}"           # docker-compose.yml에서 공개한 호스트 포트
for ipt in iptables ip6tables; do
  if ! $ipt -n -L DOCKER-USER >/dev/null 2>&1; then
    echo "$ipt: DOCKER-USER 체인 없음 (도커 미기동?) - 건너뜀" >&2
    continue
  fi
  for i in $IFACES; do
    for p in $PORTS; do
      rule="-i $i -p tcp -m conntrack --ctorigdstport $p --ctdir ORIGINAL -j DROP"
      $ipt -C DOCKER-USER $rule 2>/dev/null || $ipt -I DOCKER-USER $rule
    done
  done
done
echo "port-guard 적용: IFACES=[$IFACES] PORTS=[$PORTS]"
