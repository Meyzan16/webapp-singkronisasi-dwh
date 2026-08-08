# validate-forward.ps1 - FASE A: jalankan validator forward, kirim vonis ke Telegram.
# Dipanggil Task Scheduler harian (mis. 06:30, saat backend masih hidup).
# Hanya lapor bila ada isi; endpoint/DB read-only.

$ErrorActionPreference = 'Stop'
$Repo   = 'D:\kerja\Apps\workspace\agents-trading'
$Py     = Join-Path $Repo 'backend\.venv\Scripts\python.exe'
$Script = Join-Path $Repo 'ops\forward_validate.py'
$Notify = Join-Path $Repo 'ops\send-telegram.ps1'
$Log    = Join-Path $Repo 'ops\logs\forward-validate.log'

Push-Location (Join-Path $Repo 'backend')
try {
    $out = & $Py $Script 2>&1 | Select-Object -Last 1
} finally { Pop-Location }

if ($out) {
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $out" | Out-File -FilePath $Log -Append -Encoding utf8
    $brain = [char]::ConvertFromUtf32(0x1F52C)   # microscope
    & $Notify "$brain $out"
}
