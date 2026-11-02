# 사용: . .\tools\send.ps1  (점-소싱, $key에 장치 API 키가 있어야 함)  →  Send -79.8 / Send -65 20
function Send($temp, $secAgo = 0, $door = "false") {
    $ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $secAgo
    $b = '{"device_id":"freezer-01","ts":' + $ts + ',"temp_c":' + $temp + ',"door_open":' + $door + ',"sensor_fault":0}'
    $p = @{
        Uri         = "http://localhost:8000/api/v1/readings"
        Method      = "Post"
        Headers     = @{ "X-API-Key" = $key }
        ContentType = "application/json"
        Body        = $b
    }
    Invoke-RestMethod @p | ConvertTo-Json -Compress
}
