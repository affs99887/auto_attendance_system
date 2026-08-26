[CmdletBinding()]
param(
    [switch]$Preview,
    [switch]$Elevated,
    [string]$ResultFile
)

# Keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less scripts with
# the system code page, so non-ASCII source text can be corrupted on some PCs.

$ErrorActionPreference = 'Stop'

function Write-OperationResult {
    param(
        [bool]$Success,
        [int]$MatchedCount,
        [int]$StoppedCount,
        [int]$RemainingCount,
        [string]$Message
    )

    $result = [PSCustomObject]@{
        success        = $Success
        matchedCount   = $MatchedCount
        stoppedCount   = $StoppedCount
        remainingCount = $RemainingCount
        message        = $Message
    }

    if ($ResultFile) {
        try {
            $json = $result | ConvertTo-Json -Compress
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($ResultFile, $json, $utf8)
        } catch {
            Write-Host "[ERROR] Unable to write the result file: $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    return $result
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ClaudeMatchReason {
    param(
        [Parameter(Mandatory = $true)]
        $Process
    )

    $name = [string]$Process.Name
    $path = [string]$Process.ExecutablePath
    $commandLine = [string]$Process.CommandLine

    # Claude Desktop and the native Claude Code executable.
    if ($name -match '^(?i:claude|claude-code)(?:[-_].*)?(?:\.exe)?$') {
        return 'Claude executable name'
    }

    # Claude Desktop helpers (for example ChromeNativeHost) live below a
    # dedicated Claude directory. Claude Code installed by npm lives below the
    # @anthropic-ai\claude-code package directory.
    if (
        $path -match '(?i)[\\/]Claude[\\/]' -or
        $path -match '(?i)[\\/]@anthropic-ai[\\/]claude-code[\\/]' -or
        $path -match '(?i)[\\/]Claude(?:-Code)?\.exe$'
    ) {
        return 'Claude installation path'
    }

    # Covers node-based Claude Code launchers without treating every terminal
    # whose command line merely contains an unrelated "claude" substring as a
    # Claude process.
    if (
        $commandLine -match '(?i)@anthropic-ai[\\/]claude-code' -or
        $commandLine -match '(?i)(?:^|[\s"''])(?:claude|claude-code)(?:\.exe)?(?=$|[\s"''])'
    ) {
        return 'Claude Code command'
    }

    return $null
}

function Get-ClaudeProcessSet {
    $processes = @(Get-CimInstance Win32_Process)
    $byPid = @{}
    $childrenByParent = @{}

    foreach ($process in $processes) {
        $processId = [int]$process.ProcessId
        $parentId = [int]$process.ParentProcessId
        $byPid[$processId] = $process

        if (-not $childrenByParent.ContainsKey($parentId)) {
            $childrenByParent[$parentId] = @()
        }
        $childrenByParent[$parentId] += $processId
    }

    $targetPids = @{}
    $reasons = @{}
    $queue = New-Object System.Collections.Queue

    foreach ($process in $processes) {
        $reason = Get-ClaudeMatchReason -Process $process
        if ($null -eq $reason) {
            continue
        }

        $processId = [int]$process.ProcessId
        if (-not $targetPids.ContainsKey($processId)) {
            $targetPids[$processId] = $true
            $reasons[$processId] = $reason
            $queue.Enqueue($processId)
        }
    }

    # taskkill /T handles descendants during termination. Expanding them here
    # makes the preview and final verification cover helper processes too.
    while ($queue.Count -gt 0) {
        $parentId = [int]$queue.Dequeue()
        if (-not $childrenByParent.ContainsKey($parentId)) {
            continue
        }

        foreach ($childId in $childrenByParent[$parentId]) {
            if ($targetPids.ContainsKey($childId)) {
                continue
            }

            $targetPids[$childId] = $true
            $reasons[$childId] = "Child of Claude-related PID $parentId"
            $queue.Enqueue($childId)
        }
    }

    $targets = @(
        foreach ($processId in $targetPids.Keys) {
            $process = $byPid[[int]$processId]
            [PSCustomObject]@{
                ProcessId       = [int]$process.ProcessId
                ParentProcessId = [int]$process.ParentProcessId
                Name            = [string]$process.Name
                ExecutablePath  = [string]$process.ExecutablePath
                Reason          = [string]$reasons[[int]$processId]
            }
        }
    )

    $rootPids = @(
        foreach ($target in $targets) {
            if (-not $targetPids.ContainsKey([int]$target.ParentProcessId)) {
                [int]$target.ProcessId
            }
        }
    )

    [PSCustomObject]@{
        Targets  = $targets
        RootPids = $rootPids
    }
}

try {
    $processSet = Get-ClaudeProcessSet
} catch {
    $message = "Unable to scan Windows processes: $($_.Exception.Message)"
    Write-Host "[ERROR] $message" -ForegroundColor Red
    Write-OperationResult -Success $false -MatchedCount 0 -StoppedCount 0 -RemainingCount 0 -Message $message | Out-Null
    exit 1
}

$matchedCount = [int]$processSet.Targets.Count
if ($matchedCount -eq 0) {
    $message = 'No Claude-related processes are running.'
    Write-Host "[OK] $message" -ForegroundColor Green
    Write-OperationResult -Success $true -MatchedCount 0 -StoppedCount 0 -RemainingCount 0 -Message $message | Out-Null
    exit 0
}

Write-Host "[FOUND] Claude-related processes:" -ForegroundColor Yellow
$processSet.Targets |
    Sort-Object ProcessId |
    Select-Object ProcessId, ParentProcessId, Name, Reason, ExecutablePath |
    Format-Table -AutoSize |
    Out-Host

if ($Preview) {
    Write-Host "[PREVIEW] No process was stopped." -ForegroundColor Cyan
    exit 0
}

# Killing elevated Claude sessions requires elevation. The non-elevated pass
# scans first so opening the GUI tool does not show UAC when there is nothing to
# close. The elevated child writes the JSON result consumed by Electron.
if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        $message = 'Administrator privileges were not granted.'
        Write-OperationResult -Success $false -MatchedCount $matchedCount -StoppedCount 0 -RemainingCount $matchedCount -Message $message | Out-Null
        exit 1
    }

    try {
        $arguments = @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Hidden',
            '-File', ('"{0}"' -f $PSCommandPath),
            '-Elevated'
        )
        if ($ResultFile) {
            $arguments += @('-ResultFile', ('"{0}"' -f $ResultFile))
        }

        $child = Start-Process `
            -FilePath 'powershell.exe' `
            -ArgumentList $arguments `
            -Verb RunAs `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        exit $child.ExitCode
    } catch {
        $message = "Administrator approval was cancelled or failed: $($_.Exception.Message)"
        Write-Host "[ERROR] $message" -ForegroundColor Red
        Write-OperationResult -Success $false -MatchedCount $matchedCount -StoppedCount 0 -RemainingCount $matchedCount -Message $message | Out-Null
        exit 1
    }
}

$failedRoots = @()
foreach ($rootPid in ($processSet.RootPids | Sort-Object -Unique)) {
    $root = $processSet.Targets | Where-Object { $_.ProcessId -eq $rootPid } | Select-Object -First 1
    Write-Host "[STOP] PID $rootPid ($($root.Name)) and its child processes..."

    $taskkillOutput = @(& taskkill.exe /PID $rootPid /T /F 2>&1)
    $taskkillExitCode = $LASTEXITCODE

    if ($taskkillExitCode -ne 0) {
        # A process may exit naturally between the scan and taskkill call.
        if (Get-Process -Id $rootPid -ErrorAction SilentlyContinue) {
            $failedRoots += $rootPid
            Write-Host "[ERROR] taskkill failed for PID $rootPid (exit $taskkillExitCode)." -ForegroundColor Red
            $taskkillOutput | ForEach-Object { Write-Host "        $_" }
        } else {
            Write-Host "[OK] PID $rootPid had already exited." -ForegroundColor Green
        }
    } else {
        Write-Host "[OK] PID $rootPid process tree stopped." -ForegroundColor Green
    }
}

Start-Sleep -Milliseconds 700

try {
    $remainingSet = Get-ClaudeProcessSet
} catch {
    $message = "Processes were stopped, but final verification failed: $($_.Exception.Message)"
    Write-Host "[ERROR] $message" -ForegroundColor Red
    Write-OperationResult -Success $false -MatchedCount $matchedCount -StoppedCount 0 -RemainingCount 0 -Message $message | Out-Null
    exit 1
}

$remainingCount = [int]$remainingSet.Targets.Count
$stoppedCount = [Math]::Max(0, $matchedCount - $remainingCount)
if ($remainingCount -gt 0) {
    $message = "$remainingCount Claude-related process(es) are still running."
    Write-Host "[ERROR] $message" -ForegroundColor Red
    $remainingSet.Targets |
        Sort-Object ProcessId |
        Select-Object ProcessId, ParentProcessId, Name, Reason, ExecutablePath |
        Format-Table -AutoSize |
        Out-Host
    Write-OperationResult -Success $false -MatchedCount $matchedCount -StoppedCount $stoppedCount -RemainingCount $remainingCount -Message $message | Out-Null
    exit 1
}

$message = "Stopped all $matchedCount Claude-related process(es)."
Write-Host "[DONE] $message" -ForegroundColor Green
Write-OperationResult -Success $true -MatchedCount $matchedCount -StoppedCount $matchedCount -RemainingCount 0 -Message $message | Out-Null
exit 0
