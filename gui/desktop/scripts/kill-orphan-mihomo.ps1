# Pre-build cleanup: kill orphan mihomo.exe processes that live INSIDE this project tree.
#
# Why: mihomo is spawned by the Python side as a plain child process. If a previous run was
# hard-killed (taskkill /F without /T, Task Manager "End task", crash), mihomo is orphaned and
# keeps a lock on bin\mihomo.exe or release\win-unpacked\...\mihomo.exe, which makes
# electron-builder fail to empty its output dir ("Access is denied").
#
# Safety: matches ONLY by executable path under this project root, so it never kills a mihomo
# the user runs elsewhere. Invoked automatically by package.json predist:exe / predist:dir.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less .ps1 as the system
# code page (GBK on zh-CN), which would corrupt non-ASCII text and break parsing.

$ErrorActionPreference = 'SilentlyContinue'

# Project root: this script lives at <root>\gui\desktop\scripts\, so ..\..\.. is <root>.
$root = (Resolve-Path "$PSScriptRoot\..\..\..").Path
Write-Host "[predist] cleaning orphan mihomo under project root: $root"

$killed = 0
Get-CimInstance Win32_Process -Filter "name='mihomo.exe'" |
  Where-Object {
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)
  } |
  ForEach-Object {
    Write-Host "[predist] killing orphan mihomo (PID $($_.ProcessId)): $($_.ExecutablePath)"
    Stop-Process -Id $_.ProcessId -Force
    $killed++
  }

if ($killed -eq 0) {
    Write-Host "[predist] no in-project mihomo to clean"
} else {
    Write-Host "[predist] cleaned $killed orphan mihomo process(es)"
    Start-Sleep -Milliseconds 500   # give the OS a moment to release file handles
}

# Always succeed: cleanup failure must not block packaging (electron-builder also tries to clean).
exit 0
