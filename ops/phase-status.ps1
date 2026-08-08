# phase-status.ps1 - pelacak penyelesaian FASE. Jalankan validator forward, tentukan
# fase mana yang GATE-nya sudah lulus -> beri tahu kapan siap dieksekusi (sesi
# terawasi). Digest harian ke Telegram. TIDAK mengeksekusi fase otomatis.

$ErrorActionPreference = 'Stop'
$Repo   = 'D:\kerja\Apps\workspace\agents-trading'
$Py     = Join-Path $Repo 'backend\.venv\Scripts\python.exe'
$FScript= Join-Path $Repo 'ops\forward_validate.py'
$Notify = Join-Path $Repo 'ops\send-telegram.ps1'
$Log    = Join-Path $Repo 'ops\logs\phase-status.log'
$PidFile= Join-Path $Repo 'ops\backend.pid'
if (-not (Test-Path $PidFile)) { return }

Push-Location (Join-Path $Repo 'backend')
try { $fwd = & $Py $FScript 2>&1 | Select-Object -Last 1 } finally { Pop-Location }
if (-not $fwd) { $fwd = '(validator tak merespon)' }

if     ($fwd -match 'BERTAHAN') { $next = 'Fase A LULUS -> SIAP eksekusi Fase B (flip skor futures) / Fase C (fix lanjut). Butuh sesi terawasi.' }
elseif ($fwd -match 'MEMBURUK') { $next = 'Fase A MEMBURUK -> tinjau fix #1/#2, rollback via config futures.overextension_ceiling / weak_lane_floor bila perlu.' }
else                            { $next = 'Fase A: masih kumpul data forward. Fase B/C DITAHAN sampai bukti cukup.' }

$ico = [char]::ConvertFromUtf32(0x1F5FA)   # peta
$msg = @"
$ico PELACAK FASE
Selesai: Fase 0 (bug) - Fase 3 (monitor) - Fase 1 shadow - Fase 1b strategi #1+#2 - Fase A harness
Forward: $fwd
Berikut: $next
Independen (bisa paralel): Fase D (lifecycle model), Fase E (SPOT)
"@
& $Notify $msg
"$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $fwd" | Out-File $Log -Append -Encoding utf8
