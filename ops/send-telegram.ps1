# send-telegram.ps1 - kirim pesan ke Telegram lewat Bot API (UTF-8 aman untuk emoji).
# Baca kredensial dari ops\notify.config.json (di-gitignore, JANGAN commit):
#   { "token": "123456:ABC...", "chat_id": "12345678" }
# Pakai:  & .\send-telegram.ps1 "pesanmu"

param([Parameter(Mandatory=$true)][string]$Text)

$ErrorActionPreference = 'Stop'
$Repo = 'D:\kerja\Apps\workspace\agents-trading'
$Cfg  = Join-Path $Repo 'ops\notify.config.json'

if (-not (Test-Path $Cfg)) { return }   # belum di-setup - diam saja

function Write-NotifyLog($m) {
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" |
        Out-File -FilePath (Join-Path $Repo 'ops\logs\notify.log') -Append -Encoding utf8
}

try {
    $c = Get-Content $Cfg -Raw | ConvertFrom-Json
} catch {
    Write-NotifyLog "notif gagal: config rusak - $($_.Exception.Message)"
    return
}
if (-not $c.token -or -not $c.chat_id) { return }

$uri     = "https://api.telegram.org/bot$($c.token)/sendMessage"
$payload = @{ chat_id = $c.chat_id; text = $Text; disable_web_page_preview = $true } | ConvertTo-Json
$bytes   = [System.Text.Encoding]::UTF8.GetBytes($payload)

# Tunggu DNS `api.telegram.org` bisa di-resolve dulu. Riwayat 28 Jul 2026: saat
# mesin baru bangun/boot, jaringan belum siap → "remote name could not be
# resolved" → pesan (mis. laporan Startup) HILANG permanen krn tak ada retry.
$dnsReady = $false
for ($i = 0; $i -lt 12; $i++) {   # maks ~60 dtk (12 x 5 dtk)
    try {
        [System.Net.Dns]::GetHostEntry('api.telegram.org') | Out-Null
        $dnsReady = $true; break
    } catch { Start-Sleep -Seconds 5 }
}
if (-not $dnsReady) {
    Write-NotifyLog "notif gagal: DNS api.telegram.org belum siap setelah ~60 dtk"
    return
}

# Kirim dengan retry — tahan gangguan sesaat (sadapan SSL antivirus, jaringan goyang).
$sent = $false
$lastErr = ''
for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
        Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
            -ContentType 'application/json; charset=utf-8' -TimeoutSec 15 | Out-Null
        $sent = $true; break
    } catch {
        $lastErr = $_.Exception.Message
        if ($attempt -lt 3) { Start-Sleep -Seconds 5 }
    }
}
if (-not $sent) { Write-NotifyLog "notif gagal (3x): $lastErr" }
