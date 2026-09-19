$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = (Get-Content 'C:\Users\Tebio Zack\.kimi-code\server.token' -Raw).Trim()
$H = @{ Authorization = "Bearer $t"; 'Content-Type' = 'application/json' }
$base = 'http://127.0.0.1:5646/api/v1'

# 1) 创建会话
$body = @{ title = 'hermes-probe' } | ConvertTo-Json -Compress
$r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/sessions" -Headers $H -Body $body -TimeoutSec 30
Write-Output ("create: " + $r.StatusCode + ' ' + $r.Content.Substring(0, [Math]::Min(400, $r.Content.Length)))
$sid = ($r.Content | ConvertFrom-Json).data.id
if (-not $sid) { $sid = ($r.Content | ConvertFrom-Json).id }
Write-Output ("session_id=" + $sid)

# 2) 发一个最小 prompt
$pbody = @{ content = '只回复"收到"两个字，不要调用任何工具。' } | ConvertTo-Json -Compress
try {
  $r2 = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/sessions/$sid/prompts" -Headers $H -Body ([Text.Encoding]::UTF8.GetBytes($pbody)) -TimeoutSec 30
  Write-Output ("prompt: " + $r2.StatusCode + ' ' + $r2.Content.Substring(0, [Math]::Min(300, $r2.Content.Length)))
} catch { Write-Output ('prompt ERR: ' + $_.Exception.Message + ' | ' + $_.ErrorDetails.Message) }

# 3) 等 15 秒看状态
Start-Sleep -Seconds 15
try {
  $r3 = Invoke-WebRequest -UseBasicParsing -Uri "$base/sessions/$sid/status" -Headers @{ Authorization = "Bearer $t" } -TimeoutSec 15
  Write-Output ("status: " + $r3.Content.Substring(0, [Math]::Min(300, $r3.Content.Length)))
} catch { Write-Output ('status ERR: ' + $_.Exception.Message) }

# 4) 读消息
try {
  $r4 = Invoke-WebRequest -UseBasicParsing -Uri "$base/sessions/$sid/messages" -Headers @{ Authorization = "Bearer $t" } -TimeoutSec 15
  Write-Output ("messages len=" + $r4.Content.Length)
  Write-Output $r4.Content.Substring(0, [Math]::Min(1200, $r4.Content.Length))
} catch { Write-Output ('messages ERR: ' + $_.Exception.Message) }
