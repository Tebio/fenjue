$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = (Get-Content 'C:\Users\Tebio Zack\.kimi-code\server.token' -Raw).Trim()
$H = @{ Authorization = "Bearer $t" }
$base = 'http://127.0.0.1:5646/api/v1'

Write-Output "=== oauth/userinfo ==="
try { $r = Invoke-WebRequest -UseBasicParsing -Uri "$base/oauth/userinfo" -Headers $H -TimeoutSec 10
      Write-Output ($r.StatusCode.ToString() + ' ' + $r.Content.Substring(0, [Math]::Min(300, $r.Content.Length))) }
catch { Write-Output ('ERR ' + $_.Exception.Message) }

$cred = 'C:\Users\Tebio Zack\.kimi-code\credentials\kimi-code.json'
$before = (Get-Item $cred).LastWriteTime
Write-Output ("cred_mtime_before=" + $before.ToString('HH:mm:ss'))

Write-Output "=== providers:refresh_oauth ==="
try { $r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base/providers:refresh_oauth" -Headers $H -ContentType 'application/json' -Body '{}' -TimeoutSec 30
      Write-Output ($r.StatusCode.ToString() + ' ' + $r.Content.Substring(0, [Math]::Min(400, $r.Content.Length))) }
catch { Write-Output ('ERR ' + $_.Exception.Message + ' | ' + $_.ErrorDetails.Message) }

Start-Sleep -Seconds 3
$after = (Get-Item $cred).LastWriteTime
$c = Get-Content $cred -Raw | ConvertFrom-Json
Write-Output ("cred_mtime_after=" + $after.ToString('HH:mm:ss') + " expires_at=" + $c.expires_at)

Write-Output "=== plugins/marketplace ==="
try { $r = Invoke-WebRequest -UseBasicParsing -Uri "$base/plugins/marketplace" -Headers $H -TimeoutSec 20
      Write-Output ($r.StatusCode.ToString() + ' len=' + $r.Content.Length)
      Write-Output $r.Content.Substring(0, [Math]::Min(2500, $r.Content.Length)) }
catch { Write-Output ('ERR ' + $_.Exception.Message) }
