# Pre-build cleanup: close the locally running client BEFORE (re)packaging.
#
# Why: a running portable build (release\win-unpacked\AutoAttendance.exe) keeps file locks on the
# output dir, so electron-builder --dir / --win fails to empty it ("Access is denied"). We must
# stop the client (and the Python backend it spawned) before packaging.
#
# Safety (same rule as kill-orphan-mihomo.ps1): touch ONLY processes that live INSIDE this project
# tree. We never kill a client/python/electron the user runs from somewhere else, and we never
# touch verge-mihomo / Edge / unrelated python.
#   - AutoAttendance.exe : matched by ExecutablePath under project root
#   - backend python     : matched by CommandLine containing main.py + --gui + project root
#   - dev electron.exe   : matched by ExecutablePath under project root (node_modules\electron)
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less .ps1 as the system code
# page (GBK on zh-CN), which would corrupt non-ASCII text and break parsing.

$ErrorActionPreference = 'SilentlyContinue'

# Project root: this script lives at <root>\gui\desktop\scripts\, so ..\..\.. is <root>.
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Write-Host "[predist] closing running client under project root: $root"

$killed = 0

function Stop-Proc($p, $what) {
  Write-Host "[predist] killing $what (PID $($p.ProcessId)): $($p.ExecutablePath)"
  Stop-Process -Id $p.ProcessId -Force
  $script:killed++
}

# 1) Packaged / portable client: AutoAttendance.exe under project root (e.g. release\win-unpacked\).
#    Electron is multi-process; all child processes share the same ExecutablePath, so this matches
#    main + gpu + renderer at once.
Get-CimInstance Win32_Process -Filter "name='AutoAttendance.exe'" |
  Where-Object {
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)
  } |
  ForEach-Object { Stop-Proc $_ 'AutoAttendance.exe' }

# 2) Backend python: spawned as `python main.py --gui` (see electron\main.cjs spawnPython).
#    Match the --gui flag + main.py + a command line that points inside the project tree, so we
#    never hit a plain `python main.py` (no --gui), watchdog.py, or any unrelated python.
Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
  Where-Object {
    $_.CommandLine -and
    $_.CommandLine -like '*main.py*' -and
    $_.CommandLine -like '*--gui*' -and
    $_.CommandLine -like "*$root*"
  } |
  ForEach-Object { Stop-Proc $_ 'backend python (main.py --gui)' }

# 3) Dev client: `electron .` runs node_modules\electron\dist\electron.exe (under project root).
Get-CimInstance Win32_Process -Filter "name='electron.exe'" |
  Where-Object {
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)
  } |
  ForEach-Object { Stop-Proc $_ 'dev electron.exe' }

if ($killed -eq 0) {
    Write-Host "[predist] no in-project client to close"
} else {
    Write-Host "[predist] closed $killed client process(es)"
    Start-Sleep -Milliseconds 500   # give the OS a moment to release file handles
}

# Hard-killing the client orphans its mihomo child; reuse the existing cleanup to release that lock.
& "$PSScriptRoot\kill-orphan-mihomo.ps1"

# Always succeed: cleanup failure must not block packaging (electron-builder also tries to clean).
exit 0
