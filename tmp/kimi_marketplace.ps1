$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$t = (Get-Content 'C:\Users\Tebio Zack\.kimi-code\server.token' -Raw).Trim()
$H = @{ Authorization = "Bearer $t" }
$base = 'http://127.0.0.1:5646/api/v1'
$r = Invoke-WebRequest -UseBasicParsing -Uri "$base/plugins/marketplace" -Headers $H -TimeoutSec 30
Write-Output ("status=" + $r.StatusCode + " len=" + $r.Content.Length)
$j = $r.Content | ConvertFrom-Json
Write-Output ("top keys: " + ($j.PSObject.Properties.Name -join ', '))
# 尽量列出条目名
function Walk($o, $depth) {
  if ($depth -gt 3) { return }
  if ($o -is [array]) { foreach ($i in $o) { Walk $i ($depth+1) } }
  elseif ($o.PSObject.Properties['name'] -or $o.PSObject.Properties['id']) {
    $n = if ($o.name) { $o.name } else { $o.id }
    $d = if ($o.description) { $o.description } else { '' }
    Write-Output ("  - " + $n + " | " + $d.Substring(0, [Math]::Min(80, $d.Length)))
  }
  else { foreach ($p in $o.PSObject.Properties) { Walk $p.Value ($depth+1) } }
}
Walk $j.data 0
