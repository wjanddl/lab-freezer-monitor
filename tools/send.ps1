# 사용: . .\tools\send.ps1  (점-소싱, $key에 장치 API 키가 있어야 함)  →  Send -79.8 / Send -65 20
# 서버 주소: 기본은 Pi(Tailscale). 노트북 로컬 서버로 보내려면 점-소싱 전에 $base = "http://localhost:8000"
if (-not $base) { $base = "http://100.80.80.16:8000" }
function Send($temp, $secAgo = 0, $door = "false") {
    $ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $secAgo
    $b = '{"device_id":"freezer-01","ts":' + $ts + ',"temp_c":' + $temp + ',"door_open":' + $door + ',"sensor_fault":0}'
    $p = @{
        Uri         = "$base/api/v1/readings"
        Method      = "Post"
        Headers     = @{ "X-API-Key" = $key }
        ContentType = "application/json"
        Body        = $b
    }
    Invoke-RestMethod @p | ConvertTo-Json -Compress
}
