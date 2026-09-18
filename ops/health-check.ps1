# health-check.ps1 - cek /health tiap N menit, catat ke log, tandai insiden,
# dan kirim notifikasi Telegram (sekali per insiden, plus pesan pulih).
# Dipanggil Task Scheduler tiap 10 menit.
# Kalau backend.pid tidak ada (jam siang / weekend sebelum start), keluar diam-diam.

$ErrorActionPreference = 'Stop'
$Repo       = 'D:\kerja\Apps\workspace\agents-trading'
$HealthLog  = Join-Path $Repo 'ops\logs\health.log'
$Incident   = Join-Path $Repo 'ops\logs\INCIDENTS.log'
$PidFile    = Join-Path $Repo 'ops\backend.pid'
$StateFile  = Join-Path $Repo 'ops\logs\.health-state'   # 'ok' | 'down' - anti-spam notif
$Notify     = Join-Path $Repo 'ops\send-telegram.ps1'

function Log($file,$m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $file -Append -Encoding utf8 }
function Notify($m)    { try { & $Notify $m } catch {} }
function LastState     { if (Test-Path $StateFile) { Get-Content $StateFile -Raw } else { 'ok' } }
function SetState($s)  { $s | Out-File -FilePath $StateFile -Encoding ascii -NoNewline }

# Backend hanya "seharusnya hidup" kalau start-night sudah menulis backend.pid.
if (-not (Test-Path $PidFile)) { return }

$prev = (LastState).Trim()

try {
    # Timeout 8 detik dulu terlalu ketat: siklus scan berat (ratusan fetch kline +
    # pass outcome) memblokir event loop sampai puluhan detik, dan backend yang
    # SEHAT terbaca "tidak merespon". Diukur 8 Agu 2026: satu panggilan yang
    # timeout di 30 detik menjawab 0,35 detik beberapa saat kemudian.
    $r = Invoke-RestMethod -Uri 'http://localhost:8000/health' -TimeoutSec 30
    $agents = 'spot_scanner','spot_monitor','futures_scanner','futures_monitor'
    $down = @()
    if ($r.db -ne 'ok') { $down += 'db' }
    foreach ($a in $agents) { if (-not $r.$a.running) { $down += $a } }
    # Notifier Telegram (open/close posisi) — alarm kalau task mati atau error
    if ($r.notifier -and -not $r.notifier.running) { $down += 'notifier' }
    if ($r.notifier -and $r.notifier.last_error)   { $down += "notifier($($r.notifier.last_error))" }

    # Deteksi API key Binance ditolak / ban (mis. IP berubah -> error -2015)
    try {
        $bs = Invoke-RestMethod 'http://localhost:8000/api/v1/market/binance-status' -TimeoutSec 8
        if (-not $bs.spot_ok)    { $down += "binance-spot($($bs.spot_error))" }
        if (-not $bs.futures_ok) { $down += "binance-futures($($bs.futures_error))" }
        if ($bs.spot_banned_until -or $bs.futures_banned_until) { $down += 'binance-BANNED' }
    } catch { }

    # SCANNER MACET (bukan mati). 18 Sep 2026: futures_scanner "running: True"
    # tapi ConnectError 8 jam berturut dan last_scan_ts tak maju — health-check
    # tetap menulis "sehat". Proses beku sesudah mesin bangun dari tidur tampak
    # persis sama (PID hidup, tak satu pun siklus jalan). Kebenarannya adalah
    # last_scan_ts: kalau lebih tua dari 3x interval (min 20 menit), scanner
    # dianggap macet dan dilempar ke jalur restart di bawah — pakai pencacah
    # berturut yang sama supaya satu siklus lambat tak memicu restart.
    # BUKAN `Get-Date -UFormat %s`: di PowerShell 5.1 itu epoch dari jam LOKAL
    # (+7 jam di WIB), sehingga scanner yang baru saja jalan terbaca "421 mnt lalu".
    $nowEpoch = [double][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $stale = @()
    foreach ($a in 'spot_scanner','futures_scanner') {
        $sc = $r.$a
        if (-not $sc) { continue }
        $limit = [Math]::Max(1200, 3 * 60 * [double]($sc.interval_minutes))
        if ($sc.last_scan_ts -and (($nowEpoch - [double]$sc.last_scan_ts) -gt $limit)) {
            $stale += "$a(last_scan $([int](($nowEpoch - [double]$sc.last_scan_ts)/60)) mnt lalu)"
        }
    }
    if ($stale.Count -gt 0) { throw "SCANNER MACET: $($stale -join ', ')" }

    if ($down.Count -eq 0) {
        Log $HealthLog "OK  db+4agent sehat"
        if ($prev -ne 'ok') { Notify "PULIH: agents-trading normal lagi (db + 4 agent sehat)."; SetState 'ok' }
        # Pencacah kegagalan HARUS nol lagi begitu sehat. Tanpa ini, tiga kegagalan
        # yang terpisah berminggu-minggu akan menumpuk dan memicu restart pada
        # backend yang sebenarnya baik-baik saja.
        Remove-Item (Join-Path $Repo 'ops\logs\.health-fails') -ErrorAction SilentlyContinue
    } else {
        $msg = "INSIDEN down: $($down -join ', ')"
        Log $HealthLog $msg; Log $Incident $msg
        if ($prev -ne 'down') { Notify "ALERT agents-trading: $($down -join ', ') DOWN. Cek log di ops\logs\."; SetState 'down' }
    }
} catch {
    $msg = "INSIDEN backend TIDAK MERESPON: $($_.Exception.Message)"
    Log $HealthLog $msg; Log $Incident $msg
    if ($prev -ne 'down') { Notify "ALERT agents-trading: backend TIDAK MERESPON di :8000. Coba auto-restart..."; SetState 'down' }
    # SELF-HEAL. Dulu syaratnya "proses di backend.pid sudah mati". Dua cacat:
    #
    # 1) backend.pid mencatat PID yang SALAH. Diukur 8 Agu 2026: file berisi
    #    38552 (launcher, 0,9 MB) sementara server uvicorn sebenarnya PID 8900
    #    (1.079 MB) sebagai ANAKNYA. Launcher tetap hidup, jadi pemeriksaan
    #    liveness selalu bilang "sehat" dan self-heal TAK PERNAH menyala —
    #    meski servernya sendiri sudah mati.
    # 2) Proses yang hidup tapi WEDGED sengaja dibiarkan. Di akhir pekan (tanpa
    #    satu pun pemicu terjadwal antara Jumat 19:00 dan Senin 07:00) itu berarti
    #    sistem bisa diam berhari-hari tanpa ada yang membangunkan.
    #
    # Sekarang kebenarannya adalah ENDPOINT, bukan daftar proses: kalau /health
    # gagal beberapa kali BERTURUT-TURUT, backend direstart apa pun status
    # prosesnya. Ambang berturut-turut mencegah restart hanya karena satu siklus
    # scan yang kebetulan lambat.
    $FailFile = Join-Path $Repo 'ops\logs\.health-fails'
    $fails = 0
    if (Test-Path $FailFile) { $fails = [int]((Get-Content $FailFile -Raw).Trim()) }
    $fails++
    $fails | Out-File -FilePath $FailFile -Encoding ascii -NoNewline
    Log $HealthLog "gagal berturut-turut: $fails"

    if ($fails -ge 3) {
        Log $HealthLog "auto-restart: /health gagal $fails kali berturut -> matikan pohon proses lalu start-night"
        try {
            # Bunuh SELURUH pohon proses: mematikan launcher saja meninggalkan
            # server anak yang masih memegang port 8000, sehingga start berikutnya
            # gagal bind dan sistem tetap mati.
            # taskkill HARUS dipagari sendiri. Kalau prosesnya sudah tiada ia
            # menulis ke stderr dan mengembalikan kode != 0; di bawah
            # $ErrorActionPreference='Stop' itu MENGGAGALKAN seluruh blok restart
            # sebelum start-night sempat dipanggil — persis kasus "backend sudah
            # mati" yang justru paling butuh dihidupkan. Terbukti 8 Agu 2026:
            # "auto-restart GAGAL: ERROR: The process 38552 not found."
            $rootPid = Get-Content $PidFile -ErrorAction SilentlyContinue
            if ($rootPid -and (Get-Process -Id $rootPid -ErrorAction SilentlyContinue)) {
                try { Start-Process taskkill -ArgumentList '/PID', $rootPid, '/T', '/F' `
                        -NoNewWindow -Wait -ErrorAction SilentlyContinue } catch {}
                Start-Sleep -Seconds 3
            }
            Remove-Item $PidFile -ErrorAction SilentlyContinue
            & (Join-Path $Repo 'ops\start-night.ps1') | Out-Null
            Remove-Item $FailFile -ErrorAction SilentlyContinue
            Log $HealthLog "auto-restart selesai"
        } catch { Log $HealthLog "auto-restart GAGAL: $($_.Exception.Message)" }
    }
}

# --- Alert transisi status Adaptive Engine (shadow->canary->champion / degraded) ---
# Kirim SEKALI per transisi. Endpoint sudah dicache (murah). Kabar baik (naik level)
# maupun buruk (degraded) sama-sama dilaporkan.
$BRAIN = [char]::ConvertFromUtf32(0x1F9E0)
function EngineTransition($url, $name, $file) {
    try {
        $e = Invoke-RestMethod $url -TimeoutSec 8
        $cur = "$($e.engine_status)"
        if (-not $cur) { return }
        $prevS = if (Test-Path $file) { (Get-Content $file -Raw).Trim() } else { '' }
        if ($prevS -and $prevS -ne $cur) {
            Notify "$BRAIN ENGINE ${name}: $prevS -> $cur"
            Log $HealthLog "engine $name transisi $prevS -> $cur"
        }
        $cur | Out-File $file -Encoding ascii -NoNewline
    } catch { }
}
EngineTransition 'http://localhost:8000/api/v1/signals/adaptive-engine'         'SPOT'    (Join-Path $Repo 'ops\logs\.engine-spot')
EngineTransition 'http://localhost:8000/api/v1/signals/adaptive-engine/futures' 'FUTURES' (Join-Path $Repo 'ops\logs\.engine-fut')

# Learning :8002 — proses terpisah, tak pernah dicek sebelumnya. Kalau endpoint
# mati/timeout: bunuh PID lama (bisa beku, bukan mati — start-night hanya
# memeriksa "PID hidup") lalu start-night menyalakannya lagi.
$LearnPidFile = Join-Path $Repo 'ops\learning.pid'
if (Test-Path $LearnPidFile) {
    $lnOk = $false
    try { $lh = Invoke-RestMethod 'http://localhost:8002/health' -TimeoutSec 30; $lnOk = ($null -ne $lh) } catch {}
    if (-not $lnOk) {
        Log $HealthLog "learning :8002 tidak menjawab -> bunuh PID lama, start-night"
        $lpid = Get-Content $LearnPidFile -ErrorAction SilentlyContinue
        if ($lpid) { try { Start-Process taskkill -ArgumentList '/PID', $lpid, '/T', '/F' -WindowStyle Hidden -Wait } catch {} }
        Remove-Item $LearnPidFile -Force -ErrorAction SilentlyContinue
        try { & (Join-Path $Repo 'ops\start-night.ps1') | Out-Null; Log $HealthLog "learning auto-restart selesai" }
        catch { Log $HealthLog "learning auto-restart GAGAL: $($_.Exception.Message)" }
    }
}

# Frontend :3000 — hidupkan ulang bila mati. Ringan: satu GET, tanpa pencacah
# berturut-turut (dev server Next tak punya fase "lambat tapi hidup" seperti BE).
$FePidFile = Join-Path $Repo 'ops\frontend.pid'
if (Test-Path $FePidFile) {
    $feOk = $false
    try { $rr = Invoke-WebRequest 'http://localhost:3000/' -TimeoutSec 60 -UseBasicParsing; $feOk = ($rr.StatusCode -lt 500) } catch {}
    if (-not $feOk) {
        Log $HealthLog "frontend :3000 tidak menjawab -> start-night (Start-FrontendIfDown)"
        $fpid = Get-Content $FePidFile -ErrorAction SilentlyContinue
        if ($fpid) { try { Start-Process taskkill -ArgumentList '/PID', $fpid, '/T', '/F' -WindowStyle Hidden -Wait } catch {} }
        Remove-Item $FePidFile -Force -ErrorAction SilentlyContinue
        try { & (Join-Path $Repo 'ops\start-night.ps1') | Out-Null; Log $HealthLog "frontend auto-restart selesai" }
        catch { Log $HealthLog "frontend auto-restart GAGAL: $($_.Exception.Message)" }
    }
}
