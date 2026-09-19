$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$h = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5646/' -TimeoutSec 8).Content
$m = [regex]::Matches($h, '(?:src|href)="(/[^"]+)"')
$assets = $m | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
Write-Output "=== ASSETS ==="
$assets | Select-Object -First 20
foreach ($a in $assets) {
  if ($a -like '*.js') {
    $js = (Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:5646' + $a) -TimeoutSec 15).Content
    Write-Output ("=== " + $a + " len=" + $js.Length)
    $paths = [regex]::Matches($js, '["''](/(?:api|rpc|trpc|v1|auth|session|agent|chat|refresh)[a-zA-Z0-9/_-]*)["'']') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    $paths | Select-Object -First 40
  }
}
