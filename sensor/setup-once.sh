#!/bin/sh
# Pi에서 1회만 sudo로 실행: SPI 켜기 + kobot 사용자 서비스가 부팅 시 자동 시작되게(linger).
# 실행: sudo sh ~/freezer-monitor/sensor/setup-once.sh
set -e
raspi-config nonint do_spi 0
loginctl enable-linger kobot
sleep 1
if [ -e /dev/spidev0.0 ]; then
  echo "완료: SPI 켜짐. 창을 닫아도 됩니다."
else
  echo "SPI 적용을 위해 재부팅합니다(1~2분 뒤 자동 복구)."
  reboot
fi
