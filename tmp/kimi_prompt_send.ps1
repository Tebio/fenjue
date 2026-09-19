$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = (Get-Content 'C:\Users\Tebio Zack\.kimi-code\server.token' -Raw).Trim()
$AuthH = @{ Authorization = "Bearer $t" }
$base = 'http://127.0.0.1:5646/api/v1'
$TMPD = 'C:\Users\Tebio Zack\AppData\Local\Temp\kimi_bridge'
$sid = (Get-Content "$TMPD\sid.txt" -Raw).Trim()
Write-Output ("sid=" + $sid)

$bodyBytes = [IO.File]::ReadAllBytes("$TMPD\prompt.json")
try {
  $r2 = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/sessions/$sid/prompts" -Headers $AuthH -ContentType 'application/json; charset=utf-8' -Body $bodyBytes -TimeoutSec 60
  $c2 = $r2.Content
  Write-Output ("prompt_status=" + $r2.StatusCode)
  Write-Output $c2.Substring(0, [Math]::Min(400, $c2.Length))
} catch {
  Write-Output ("prompt_ERR " + $_.Exception.Message)
  if ($_.ErrorDetails.Message) { Write-Output ($_.ErrorDetails.Message.Substring(0, [Math]::Min(300, $_.ErrorDetails.Message.Length))) }
}

Start-Sleep -Seconds 25
$r3 = Invoke-WebRequest -UseBasicParsing -Uri "$base/sessions/$sid/status" -Headers $AuthH -TimeoutSec 15
Write-Output ("status: " + $r3.Content.Substring(0, [Math]::Min(250, $r3.Content.Length)))

$r4 = Invoke-WebRequest -UseBasicParsing -Uri "$base/sessions/$sid/messages" -Headers $AuthH -TimeoutSec 15
$c4 = $r4.Content
Write-Output ("messages_len=" + $c4.Length)
Write-Output $c4.Substring(0, [Math]::Min(2000, $c4.Length))
