@echo off
REM run_session.bat — double-click wrapper for run_session.ps1
REM Logs to logs\session.log in the project folder.

set SCRIPT=%~dp0run_session.ps1
set LOGDIR=%~dp0logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

powershell -NonInteractive -ExecutionPolicy Bypass -File "%SCRIPT%" -LogFile "%LOGDIR%\session.log"
pause
