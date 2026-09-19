$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Write-Output "=== APP.ASAR.UNPACKED ==="
Get-ChildItem 'E:\软件\kimi code\resources\app.asar.unpacked' -Recurse -Depth 3 | Select-Object -First 40 -ExpandProperty FullName
Write-Output "=== DESKTOP-DIST ==="
Get-ChildItem 'E:\软件\kimi code\resources\desktop-dist' | Select-Object -First 30 -ExpandProperty Name
Write-Output "=== BUILD ==="
Get-ChildItem 'E:\软件\kimi code\resources\build' | Select-Object -First 30 -ExpandProperty Name
