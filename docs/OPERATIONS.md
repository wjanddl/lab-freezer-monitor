# Pi 운영 (현재 Pi: Tailscale 100.80.80.16, Debian 12 bookworm, docker 29.9.2)

> ⚠ 아래 sudo 단계는 Claude Code가 직접 실행·검증하지 못했다(비밀번호 sudo). 사용자가 Pi에서 실행하고 기대 출력과 비교한다.

## 현재 네트워크 (2026-11-03 확인)
- wlan0 = 학교 Wi-Fi **클라이언트**(10.101.x), eth0 = 미연결, tailscale0 = 100.80.80.16
- CLAUDE.md의 목표 구조(wlan0 = ESP32용 AP)는 8단계에서 적용 예정. 그때 port-guard의 IFACES를 다시 정한다.

## 1. API 포트 외부망 차단 + OLED 자동 시작 (1회)
```sh
sudo install -m 755 -o root -g root ~/freezer-monitor/pi-setup/port-guard.sh /usr/local/sbin/freezer-port-guard.sh
sudo install -m 644 ~/freezer-monitor/pi-setup/freezer-port-guard.service /etc/systemd/system/
sudo install -m 644 ~/freezer-monitor/pi-setup/oled/freezer-oled.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now freezer-port-guard.service freezer-oled.service
systemctl is-active freezer-port-guard freezer-oled
sudo iptables -S DOCKER-USER | grep 8000; sudo ip6tables -S DOCKER-USER | grep 8000
```
기대 출력:
- `active` 두 줄
- `-A DOCKER-USER -i eth0 -p tcp -m conntrack --ctorigdstport 8000 --ctdir ORIGINAL -j DROP` 와 같은 wlan0 줄 (iptables, ip6tables 각각)

확인:
- 노트북(Tailscale): `curl http://100.80.80.16:8000/health` → `{"status":"ok","influx":true}` (계속 됨)
- 학교 Wi-Fi에 붙은 폰/PC(Tailscale 끔): `http://10.101.53.219:8000/health` → 응답 없음(시간 초과) 이어야 정상
- 재부팅 후에도 위 두 가지 동일, OLED가 자동으로 켜짐
- OLED 로그: `journalctl -u freezer-oled -n 20`

- ip6tables 줄이 없고 서비스 로그(`journalctl -u freezer-port-guard`)에 "DOCKER-USER 체인 없음"이 있으면 도커가 IPv6 규칙을 안 쓰는 설정이라 IPv6 공개 포트도 막아야 함 → 알려줄 것

되돌리기:
```sh
sudo systemctl disable --now freezer-port-guard freezer-oled
for t in iptables ip6tables; do for i in wlan0 eth0; do sudo $t -D DOCKER-USER -i $i -p tcp -m conntrack --ctorigdstport 8000 --ctdir ORIGINAL -j DROP; done; done
```
