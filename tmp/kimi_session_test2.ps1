$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = (Get-Content 'C:\Users\Tebio Zack\.kimi-code\server.token' -Raw).Trim()
$AuthH = @{ Authorization = "Bearer $t" }
$base = 'http://127.0.0.1:5646/api/v1'

# 1) 创建会话（带 cwd）
$body = '{"title":"hermes-probe","metadata":{"cwd":"C:\\Users\\Tebio Zack"}}'
$r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/sessions" -Headers $AuthH -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 30
$j = $r.Content | ConvertFrom-Json
Write-Output ("create_code=" + $j.code)
$sid = $j.data.id
if (-not $sid) { $sid = $j.data.session_id }
Write-Output ("session_id=" + $sid)
Write-Output ($r.Content.Substring(0, [Math]::Min(500, $r.Content.Length)))

if ($sid) {
  # 2) 发最小 prompt（Unicode 转义防编码问题）
  $pbody = '{"content":"\u53ea\u56de\u590d\u201c\u6536\u5230\u201d\u4e24\u4e2a\u5b57\uff0c\u4e0d\u8981\u8c03\u7528\u4efb\u4f55\u5de5\u5177\u3002"}'
  try {
    $r2 = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/sessions/$sid/prompts" -Headers $AuthH -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($pbody)) -TimeoutSec 30
    $c2 = $r2.Content
    Write-Output ("prompt_status=" + $r2.StatusCode)
    Write-Output $c2.Substring(0, [Math]::Min(400, $c2.Length))
  } catch {
    Write-Output ("prompt_ERR " + $_.Exception.Message)
  }

  Start-Sleep -Seconds 20

  # 3) 状态 + 消息
  try {
    $r3 = Invoke-WebRequest -UseBasicParsing -Uri "$base/sessions/$sid/status" -Headers $AuthH -TimeoutSec 15
    $c3 = $r3.Content
    Write-Output ("status: " + $c3.Substring(0, [Math]::Min(300, $c3.Length)))
  } catch { Write-Output ("status_ERR " + $_.Exception.Message) }
  try {
    $r4 = Invoke-WebRequest -UseBasicParsing -Uri "$base/sessions/$sid/messages" -Headers $AuthH -TimeoutSec 15
    $c4 = $r4.Content
    Write-Output ("messages_len=" + $c4.Length)
    Write-Output $c4.Substring(0, [Math]::Min(1500, $c4.Length))
  } catch { Write-Output ("messages_ERR " + $_.Exception.Message) }
}
