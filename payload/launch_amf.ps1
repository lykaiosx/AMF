param(
    [switch]$SilentFailure
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppPath = Join-Path $InstallDir "start_amf.py"
$PythonwFile = Join-Path $InstallDir "pythonw_path.txt"
$PythonFile = Join-Path $InstallDir "python_path.txt"
$LogFile = Join-Path $InstallDir "startup.log"

function Read-PathFile([string]$Path) {
    if (Test-Path $Path) {
        return (Get-Content -Path $Path -Raw).Trim()
    }
    return $null
}

$pythonw = Read-PathFile $PythonwFile
$python = Read-PathFile $PythonFile

if (-not $pythonw -or -not (Test-Path $pythonw)) {
    if (-not $SilentFailure) {
        [System.Windows.Forms.MessageBox]::Show(
            "AMF could not find its Python GUI runtime.`r`n`r`nPlease run AMF Setup again.",
            "AMF",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    exit 1
}

try {
    $process = Start-Process `
        -WindowStyle Normal `
        -FilePath $pythonw `
        -ArgumentList @('"' + $AppPath + '"') `
        -WorkingDirectory $InstallDir `
        -PassThru

    Start-Sleep -Milliseconds 1500

    if (-not $process.HasExited) {
        exit 0
    }
}
catch {
    # Fall through to diagnostic launch.
}

if (-not $python -or -not (Test-Path $python)) {
    if (-not $SilentFailure) {
        [System.Windows.Forms.MessageBox]::Show(
            "AMF failed to start, and its diagnostic Python runtime is unavailable.`r`n`r`nPlease run AMF Setup again.",
            "AMF",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    exit 1
}

try {
    Remove-Item $LogFile -Force -ErrorAction SilentlyContinue

    $diag = Start-Process `
        -FilePath $python `
        -ArgumentList @('"' + $AppPath + '"') `
        -WorkingDirectory $InstallDir `
        -RedirectStandardError $LogFile `
        -RedirectStandardOutput (Join-Path $InstallDir "startup-output.log") `
        -PassThru `
        -WindowStyle Hidden

    Start-Sleep -Milliseconds 1800

    if (-not $diag.HasExited) {
        # Diagnostic path actually launched successfully; leave it running.
        exit 0
    }
}
catch {
    $_ | Out-File -FilePath $LogFile -Encoding UTF8
}

$message = "AMF failed to start."

if (Test-Path $LogFile) {
    $details = (Get-Content -Path $LogFile -Raw).Trim()
    if ($details) {
        if ($details.Length -gt 1600) {
            $details = $details.Substring($details.Length - 1600)
        }

        $message += "`r`n`r`nStartup error:`r`n" + $details
    }
}

$message += "`r`n`r`nA startup log was saved to:`r`n" + $LogFile

if (-not $SilentFailure) {
    [System.Windows.Forms.MessageBox]::Show(
        $message,
        "AMF",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

exit 1
