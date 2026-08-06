# start-night.ps1 - nyalakan infra + backend (mode embedded, agent auto-start).
# Dipanggil Windows Task Scheduler tiap Sen-Jum 19:00 WIB.
# Backend jalan TANPA --reload (lebih stabil untuk run panjang; reload juga
# tidak mengawasi folder agents/).

$ErrorActionPreference = 'Stop'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$Backend = Join-Path $Repo 'backend'
$Py      = Join-Path $Backend '.venv\Scripts\python.exe'
$LogDir  = Join-Path $Repo 'ops\logs'
$PidFile = Join-Path $Repo 'ops\backend.pid'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutLog  = Join-Path $LogDir "backend-$stamp.out.log"
$ErrLog  = Join-Path $LogDir "backend-$stamp.err.log"
$RunLog  = Join-Path $LogDir 'night-runner.log'

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $RunLog -Append }

# Tanpa penjaga di bawah ini, kegagalan APA PUN sesudah baris ini menghilang
# tanpa jejak: $ErrorActionPreference='Stop' membuat error pertama menghentikan
# skrip, dan tak ada satu pun baris log yang menjelaskan kenapa.
# Bukti nyata: 5 & 6 Agu 2026 START-NIGHT tercatat "dipicu" pada 19:00 lalu
# senyap — backend tak pernah menyala semalaman, dan Task Scheduler hanya
# melaporkan kode 0x40010004 (proses dihentikan) tanpa konteks apa pun.
trap {
    Log ("GAGAL di baris {0}: {1}" -f $_.InvocationInfo.ScriptLineNumber, $_.Exception.Message)
    Log "=== START-NIGHT BERHENTI (tidak tuntas) ==="
    exit 1
}

Log "=== START-NIGHT dipicu ==="

# 1) Infra: pastikan Docker Desktop HIDUP, lalu postgres + redis, lalu TUNGGU
#    Postgres benar-benar menerima koneksi.
#    Riwayat 30 Jul 2026: backend menyala 18:07 saat Postgres belum siap
#    ("WinError 1225 refused"), flag _db_available terkunci False dan learning
#    mati diam-diam berjam-jam (cached_keys=0). `docker compose up -d` langsung
#    kembali sebelum DB siap, jadi ia TIDAK cukup — harus ditunggu.

# 1a) Docker engine hidup? Kalau tidak, nyalakan Docker Desktop dan tunggu.
$dockerOk = $false
try { docker info 2>&1 | Out-Null; $dockerOk = ($LASTEXITCODE -eq 0) } catch { $dockerOk = $false }
if (-not $dockerOk) {
    Log "docker engine mati - menyalakan Docker Desktop"
    $dd = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dd) {
        try { Start-Process $dd -WindowStyle Hidden } catch { Log "gagal start Docker Desktop: $($_.Exception.Message)" }
    } else {
        Log "PERINGATAN Docker Desktop tidak ditemukan di $dd"
    }
    for ($i = 0; $i -lt 60; $i++) {          # tunggu maks ~5 menit
        Start-Sleep -Seconds 5
        try { docker info 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break } } catch { }
    }
    Log ("docker engine " + $(if ($dockerOk) { "siap" } else { "TETAP MATI setelah 5 menit" }))
}

# 1b) Container infra
try {
    Push-Location $Repo
    docker compose up postgres redis -d | Out-Null
    Log "docker: postgres + redis up"
} catch {
    Log "PERINGATAN docker gagal: $($_.Exception.Message)"
} finally { Pop-Location }

# 1c) TUNGGU Postgres benar-benar menerima koneksi (bukan sekadar container "Up").
$pgReady = $false
for ($i = 0; $i -lt 40; $i++) {              # maks ~2 menit
    try {
        docker exec agents-trading-postgres-1 pg_isready 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $pgReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}
if ($pgReady) {
    Log "postgres siap menerima koneksi"
} else {
    Log "PERINGATAN postgres belum siap setelah ~2 menit - backend tetap dijalankan (watchdog DB akan menyusul)"
}

# 2) Jangan start dobel - kalau PID lama masih hidup, TETAP kirim laporan lalu selesai.
#    Riwayat 28 Jul 2026: cabang ini dulu `return` diam → tak ada laporan Startup
#    padahal owner mengharapkannya. Sekarang tetap lapor "sudah jalan".
if (Test-Path $PidFile) {
    $old = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Log "backend sudah jalan (PID $old) - lewati start, kirim laporan status"
        try { & (Join-Path $Repo 'ops\report-telegram.ps1') 'Startup (backend sudah jalan)' | Out-Null; Log "laporan dikirim" }
        catch { Log "laporan gagal: $($_.Exception.Message)" }
        # Penanda tuntas WAJIB ada juga di jalur keluar-awal ini. Tanpa itu,
        # kondisi normal "backend sudah jalan" terlihat SAMA PERSIS dengan skrip
        # yang mati di tengah jalan — dan penandanya jadi tak bisa dipercaya.
        Log "=== START-NIGHT SELESAI (backend sudah jalan) ==="
        return
    }
}

# 3) Start backend (uvicorn, no-reload), detached
$uvArgs = '-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000'
$p = Start-Process -FilePath $Py -ArgumentList $uvArgs -WorkingDirectory $Backend `
        -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
        -WindowStyle Hidden -PassThru
$p.Id | Out-File -FilePath $PidFile -Encoding ascii
Log ("backend START (PID {0}) log {1}" -f $p.Id, $OutLog)

# 4) Tunggu backend sehat, lalu kirim laporan menyeluruh ke Telegram
Start-Sleep -Seconds 25
for ($i = 0; $i -lt 8; $i++) {
    try { $hc = Invoke-RestMethod 'http://localhost:8000/health' -TimeoutSec 5; if ($hc.status -eq 'ok') { break } } catch {}
    Start-Sleep -Seconds 5
}
try { & (Join-Path $Repo 'ops\report-telegram.ps1') 'Startup Malam' | Out-Null; Log "laporan startup dikirim" }
catch { Log "laporan startup gagal: $($_.Exception.Message)" }

# Penanda tuntas. Ketiadaan baris ini di night-runner.log = skrip mati di tengah
# jalan, dan baris "GAGAL di baris N" tepat di atasnya menunjukkan di mana.
Log "=== START-NIGHT SELESAI ==="
