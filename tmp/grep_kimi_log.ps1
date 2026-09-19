$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$log = 'C:\Users\Tebio Zack\.kimi-code\logs\kimi-code.log'
$lines = Get-Content $log
$hits = $lines | Select-String -Pattern 'skill' | Select-Object -Last 20
foreach ($h in $hits) { $h.Line.Substring(0, [Math]::Min(240, $h.Line.Length)) }
