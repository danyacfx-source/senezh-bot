param([switch]$SkipRestart)
$ErrorActionPreference = "Stop"
$root = "C:\Users\Admin\Documents\Default Project\senezh-bot"
$logDir = "$env:USERPROFILE\duckdns"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$vo = "$logDir\lhr.out.log"
$v = "$logDir\lhr.err.log"

Get-Process ssh -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Remove-Item $vo, $v -ErrorAction SilentlyContinue

Start-Process ssh -ArgumentList `
  '-o', 'StrictHostKeyChecking=no', `
  '-o', 'ServerAliveInterval=30', `
  '-o', 'ServerAliveCountMax=3', `
  '-o', 'ConnectTimeout=20', `
  '-o', 'ExitOnForwardFailure=yes', `
  '-R', '80:127.0.0.1:17890', `
  'nokey@localhost.run' `
  -RedirectStandardOutput $vo -RedirectStandardError $v -WindowStyle Hidden

$u = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Seconds 1
  $m = Select-String -Path $vo, $v -Pattern 'https://[a-z0-9]+\.lhr\.life' -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($m) { $u = $m.Matches.Value; break }
}
if (-not $u) { Write-Output "TUNNEL_FAILED"; Get-Content $v -Tail 15 -ErrorAction SilentlyContinue; exit 1 }

Write-Output "PANEL_URL=$u"
Set-Content -Path "$root\panel_url.txt" -Value $u

if (-not $SkipRestart) {
  $envPath = "$root\.env"
  $lines = @(Get-Content $envPath)
  $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -like 'PANEL_PUBLIC_URL=*') { $lines[$i] = "PANEL_PUBLIC_URL=$u"; $found = $true }
  }
  if (-not $found) { $lines += "PANEL_PUBLIC_URL=$u" }
  Set-Content -Path $envPath -Value $lines

  Start-Sleep -Seconds 3
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | `
    Where-Object { $_.CommandLine -like '*bot.py*' -and $_.CommandLine -notlike '*Desktop*' -and $_.CommandLine -notlike '*discord-role-bot*' } | `
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  Start-Process pythonw.exe -ArgumentList 'bot.py' -WorkingDirectory $root -RedirectStandardOutput "$root\bot_out.log" -RedirectStandardError "$root\bot_err.log"
  Write-Output "BOT_RESTARTED=1"
}

Write-Output "PUBLIC_URL=$u"