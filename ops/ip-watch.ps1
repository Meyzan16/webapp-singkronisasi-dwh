# ip-watch.ps1 - pantau IP publik rumah; kalau BERUBAH, alarm Telegram dengan
# IP baru siap-copy + instruksi update whitelist Binance (langkah 2FA tetap manual).
# Dipanggil Task Scheduler tiap 15 menit. Ringan.

$ErrorActionPreference = 'Stop'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$LastIp  = Join-Path $Repo 'ops\last-ip.txt'
$IpLog   = Join-Path $Repo 'ops\logs\ip.log'
$Notify  = Join-Path $Repo 'ops\send-telegram.ps1'

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $IpLog -Append -Encoding utf8 }

# Ambil IP publik (beberapa sumber sebagai cadangan)
$ip = $null
foreach ($u in 'https://api.ipify.org','https://ifconfig.me/ip','https://icanhazip.com') {
    try { $ip = (Invoke-RestMethod $u -TimeoutSec 8).ToString().Trim(); if ($ip -match '^\d{1,3}(\.\d{1,3}){3}$') { break } else { $ip = $null } } catch { $ip = $null }
}
if (-not $ip) { Log "gagal ambil IP publik dari semua sumber"; return }

$prev = if (Test-Path $LastIp) { (Get-Content $LastIp -Raw).Trim() } else { $null }

if ($prev -eq $ip) { Log "OK IP tetap $ip"; return }

$ip | Out-File -FilePath $LastIp -Encoding ascii -NoNewline

if (-not $prev) {
    Log "IP awal dicatat: $ip"
    return   # pertama kali - jangan alarm, cuma catat baseline
}

$emojiPin  = [char]::ConvertFromUtf32(0x1F4CD)
$emojiWarn = [char]::ConvertFromUtf32(0x26A0)
$msg = @"
$emojiWarn IP RUMAH BERUBAH
$emojiPin IP baru: $ip
(lama: $prev)

Agent butuh IP ini di-whitelist Binance, kalau tidak API key bisa DITOLAK.
Update manual (butuh 2FA):
1. Binance > Account > API Management
2. Pilih key > Edit restrictions
3. Ganti IP whitelist ke: $ip
4. Simpan + approve Authenticator

Sampai diupdate, watchdog akan alarm kalau key ditolak.
"@

& $Notify $msg
Log "ALARM IP berubah $prev -> $ip (notif terkirim)"
