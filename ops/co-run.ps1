# co-run.ps1 - jalankan CO (Claude Code headless, Opus 5) sekali sehari.
# Dipanggil Task Scheduler AgentsTrading-CO tiap 06:15 WIB (backend MASIH hidup,
# baru berhenti 07:00) supaya CO bisa membaca API + DB + log semalam penuh.
#
# Pengaman:
#   - guard backend.pid: kalau agents memang tak jalan, keluar diam-diam
#   - --max-budget-usd: batas biaya per run (default 5)
#   - brief (ops/co-brief.md) melarang restart backend & mewajibkan flag OFF
#     untuk perubahan yang menyentuh keputusan trading
# Pakai manual:  & .\co-run.ps1            (budget default)
#                & .\co-run.ps1 -BudgetUsd 2

param(
    [double]$BudgetUsd = 5.0,
    [string]$Model     = 'claude-opus-5',
    [switch]$Force                     # jalankan walau backend sedang mati
)

$ErrorActionPreference = 'Continue'
$Repo    = 'D:\kerja\Apps\workspace\agents-trading'
$Brief   = Join-Path $Repo 'ops\co-brief.md'
$Notify  = Join-Path $Repo 'ops\send-telegram.ps1'
$PidFile = Join-Path $Repo 'ops\backend.pid'
$LogDir  = Join-Path $Repo 'ops\logs'
$Stamp   = (Get-Date).ToString('yyyyMMdd-HHmmss')
$OutFile = Join-Path $LogDir "co-$Stamp.log"
$RunLog  = Join-Path $LogDir 'co-run.log'

function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $RunLog -Append -Encoding utf8 }

if (-not (Test-Path $Brief)) { Log 'brief tidak ada - batal'; return }

# Backend harus hidup supaya CO bisa membaca API (DB tetap hidup 24 jam).
if (-not $Force) {
    $curPid = (Get-Content $PidFile -ErrorAction SilentlyContinue)
    if (-not $curPid -or -not (Get-Process -Id $curPid -ErrorAction SilentlyContinue)) {
        Log 'backend tidak jalan - lewati run (pakai -Force untuk memaksa)'
        return
    }
}

$brief = Get-Content $Brief -Raw
$prompt = @"
$brief

---
Jalankan protokol di atas SEKARANG untuk tanggal $((Get-Date).ToString('yyyy-MM-dd')).
Mulai dengan mengukur data hidup, lalu kerjakan 1-3 perbaikan berdampak tertinggi.
Akhiri dengan menulis laporan ke docs/co-reports/$((Get-Date).ToString('yyyy-MM-dd')).md.
"@

Log "CO START model=$Model budget=`$$BudgetUsd log=$OutFile"
Push-Location $Repo
try {
    # bypassPermissions wajib: sesi tak terawasi, prompt izin akan menggantung.
    # Pagar keselamatan ada di BRIEF (flag OFF, verifikasi, dilarang restart).
    $prompt | & claude -p `
        --model $Model `
        --permission-mode bypassPermissions `
        --max-budget-usd $BudgetUsd `
        2>&1 | Tee-Object -FilePath $OutFile
    $code = $LASTEXITCODE
} catch {
    $code = 1
    "EXCEPTION: $($_.Exception.Message)" | Out-File -FilePath $OutFile -Append -Encoding utf8
} finally {
    Pop-Location
}

Log "CO SELESAI exit=$code"

# --- Ringkas ke Telegram (ekor keluaran; laporan penuh ada di docs/co-reports/) ---
$tail = if (Test-Path $OutFile) { (Get-Content $OutFile -Tail 25) -join "`n" } else { '(tak ada keluaran)' }
if ($tail.Length -gt 2500) { $tail = $tail.Substring($tail.Length - 2500) }
$head = if ($code -eq 0) { "$([char]::ConvertFromUtf32(0x1F9D1)) CO harian SELESAI" }
        else            { "$([char]::ConvertFromUtf32(0x26A0)) CO harian exit=$code" }
$report = Join-Path $Repo ("docs\co-reports\" + (Get-Date).ToString('yyyy-MM-dd') + '.md')
$hasReport = if (Test-Path $report) { 'laporan: docs/co-reports/' + (Get-Date).ToString('yyyy-MM-dd') + '.md' }
             else { 'laporan TIDAK dibuat - cek ' + (Split-Path $OutFile -Leaf) }

& $Notify "$head`n$hasReport`n`n--- ekor keluaran ---`n$tail"

# Buang log CO lebih tua dari 30 hari
Get-ChildItem $LogDir -Filter 'co-*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue
