$log = "$env:USERPROFILE\duckdns\duck.log"
$uri = "https://www.duckdns.org/update?domains=embed-panel&token=a4b47562-02de-49c1-a967-f249b0340076&ip="
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\duckdns" | Out-Null
try {
  $res = (New-Object System.Net.WebClient).DownloadString($uri)
  Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $res)
} catch {
  Add-Content -Path $log -Value ("{0} ERROR {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message)
}