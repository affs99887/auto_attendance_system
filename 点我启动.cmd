@echo off
rem ============================================================================
rem  Launch the portable (no-install) AAS build from the project root.
rem  The build is produced by:  cd gui\desktop  &&  npm run dist:dir
rem  and lives at:  <project root>\release\win-unpacked\AutoAttendance.exe
rem ============================================================================
setlocal
set "EXE=%~dp0release\win-unpacked\AutoAttendance.exe"
if exist "%EXE%" (
  echo Starting portable AAS ...
  start "" "%EXE%"
) else (
  echo [ERROR] Portable build not found:
  echo     %EXE%
  echo.
  echo Build it first:
  echo     cd gui\desktop  ^&^&  npm run dist:dir
  echo.
  pause
)
endlocal
