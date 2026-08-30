$ErrorActionPreference = "Stop"
$root = "C:\Users\Admin\Documents\Default Project\senezh-bot"
$cf = "$root\deploy\cloudflared.exe"
$log = "$env:USERPROFILE\duckdns\cf_tunnel.log"
$errLog = "$env:USERPROFILE\duckdns\cf_tunnel.err"

if (-not (Test-Path $cf)) {
  Write-Error "cloudflared not found: $cf"
  exit 1
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

Start-Process -FilePath $cf -ArgumentList 'tunnel', '--url', 'http://127.0.0.1:17890', '--protocol', 'http2', '--no-autoupdate' `
  -RedirectStandardOutput $log -RedirectStandardError $errLog -WindowStyle Hidden

$url = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Seconds 1
  $txt = Get-Content $log -Raw -ErrorAction SilentlyContinue
  if ($txt -and $txt -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
    $url = $matches[0]
    break
  }
}

if (-not $url) {
  Write-Output "TUNNEL_URL=FAILED"
  Get-Content $errLog -Tail 20 -ErrorAction SilentlyContinue
  exit 1
}

Write-Output "TUNNEL_URL=$url"

$envPath = "$root\.env"
if (Test-Path $envPath) {
  $lines = @(Get-Content $envPath)
  $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -like 'PANEL_PUBLIC_URL=*') {
      $lines[$i] = "PANEL_PUBLIC_URL=$url"
      $found = $true
    }
  }
  if (-not $found) { $lines += "PANEL_PUBLIC_URL=$url" }
  Set-Content -Path $envPath -Value $lines -Encoding ASCII
  Write-Output "ENV_UPDATED=1"
}