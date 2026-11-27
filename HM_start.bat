@echo off
title HM-AI-V6 Live Trading Terminal
cd /d "%~dp0"
set "JARVIS_CONFIRM_LIVE=1"
echo ======================================================================
echo           Starting HM-AI-V6 (HM Algo 6.0) Live Trading Terminal
echo ======================================================================
if exist "C:\Users\musu9\AppData\Local\Programs\Python\Python312\python.exe" (
    "C:\Users\musu9\AppData\Local\Programs\Python\Python312\python.exe" tools\hm_supervisor.py %*
) else (
    py -3.12 tools\hm_supervisor.py %* 2>nul || python tools\hm_supervisor.py %*
)
pause
