$env:JARVIS_CONFIRM_LIVE = "1"
Write-Host "====================================================================="
Write-Host "          Starting HM-AI-V6 (HM Algo 6.0) Live Trading Terminal"
Write-Host "====================================================================="
$py312 = "C:\Users\musu9\AppData\Local\Programs\Python\Python312\python.exe"
if (Test-Path $py312) {
    & $py312 "$PSScriptRoot\tools\hm_supervisor.py" $args
} else {
    python "$PSScriptRoot\tools\hm_supervisor.py" $args
}
