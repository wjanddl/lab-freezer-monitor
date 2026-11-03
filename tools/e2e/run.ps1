# E2E 실행 (노트북, 프로젝트 루트에서): powershell -File tools\e2e\run.ps1
# 운영 스택/데이터와 분리된 freezer-e2e 프로젝트로 띄우고, 끝나면 전용 볼륨까지 삭제한다. 약 2분.
$f = "tools/e2e/docker-compose.e2e.yml"
docker compose -p freezer-e2e -f $f build
docker compose -p freezer-e2e -f $f run --rm runner
$code = $LASTEXITCODE
docker compose -p freezer-e2e -f $f --profile run down -v
exit $code
