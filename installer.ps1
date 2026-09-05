$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Version = "4.8.1"
$SetupDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PayloadDir = Join-Path $SetupDir "payload"

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\AMF"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartLink = Join-Path $StartMenuDir "AMF.lnk"
$DesktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "AMF.lnk"

$UninstallReg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AMF"

function Installed-Version {
    try {
        return (Get-ItemProperty -Path $UninstallReg -Name DisplayVersion -ErrorAction Stop).DisplayVersion
    } catch {
        return $null
    }
}

function Find-Python {
    $found = New-Object System.Collections.Generic.List[string]

    # WindowsApps\python.exe is often only a Store alias. It can start a
    # callback/redirect stub and is not a usable interpreter for installation.
    try {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and
            -not $cmd.Source.ToLowerInvariant().Contains("\\windowsapps\\")) {
            $found.Add($cmd.Source)
        }
    } catch {}

    $localPython = Join-Path $env:LOCALAPPDATA "Python"

    if (Test-Path $localPython) {
        Get-ChildItem `
            -Path $localPython `
            -Filter python.exe `
            -Recurse `
            -ErrorAction SilentlyContinue |
            ForEach-Object { $found.Add($_.FullName) }
    }

    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python314\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) { $found.Add($candidate) }
    }

    foreach ($candidate in ($found | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            & $candidate -c "import sys; assert sys.version_info >= (3,10); print(sys.executable)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }

    return $null
}

function Pythonw-For([string]$Python) {
    if (-not $Python) { return $null }

    $candidate = Join-Path (Split-Path -Parent $Python) "pythonw.exe"

    if (Test-Path $candidate) {
        return $candidate
    }

    return $null
}

function Stop-AMF {
    Get-Process -Name "AMF" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    try {
        $needle = (Join-Path $InstallDir "app.py").ToLowerInvariant()

        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.Name -in @("python.exe","pythonw.exe")) -and
                $_.CommandLine -and
                $_.CommandLine.ToLowerInvariant().Contains($needle)
            } |
            ForEach-Object {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
    } catch {}

    Start-Sleep -Milliseconds 700
}

function New-AMFShortcut([string]$ShortcutPath, [string]$PythonwPath) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)

    # IMPORTANT: Windows Search launches the exact verified runtime directly.
    $shortcut.TargetPath = $PythonwPath
    $shortcut.Arguments = '"' + (Join-Path $InstallDir "start_amf.py") + '"'
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = (Join-Path $InstallDir "AMF.ico") + ",0"
    $shortcut.Description = "AMF $Version"
    $shortcut.Save()
}

function Set-InstallProgress([int]$Value, [string]$Text) {
    $progress.Value = [Math]::Max(0, [Math]::Min(100, $Value))
    $status.Text = $Text
    $percent.Text = "$Value%"
    $form.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
}

$installed = Installed-Version
$hasInstall = (Test-Path $InstallDir) -or ($null -ne $installed)

if ($hasInstall) {
    if ($installed -eq $Version) {
        $prompt = "AMF $Version is already installed.`r`n`r`nReinstall this version?"
    } elseif ($installed) {
        $prompt = "AMF $installed is currently installed.`r`n`r`nUpdate to AMF $Version?"
    } else {
        $prompt = "An existing AMF installation was detected.`r`n`r`nUpdate/reinstall it with AMF $Version?"
    }
} else {
    $prompt = "Install AMF $Version?"
}

$answer = [System.Windows.Forms.MessageBox]::Show(
    $prompt + "`r`n`r`nYour settings, saved sources, and cart will be preserved.",
    "AMF Setup",
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
)

if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
    exit 0
}

# ------------------------
# Visible installer window
# ------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = "AMF Setup"
$form.StartPosition = "CenterScreen"
$form.ClientSize = New-Object System.Drawing.Size(540,235)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(17,17,20)

try {
    $form.Icon = New-Object System.Drawing.Icon(
        (Join-Path $PayloadDir "AMF.ico")
    )
} catch {}

$title = New-Object System.Windows.Forms.Label
$title.Text = if ($hasInstall) { "Updating AMF" } else { "Installing AMF" }
$title.ForeColor = [System.Drawing.Color]::White
$title.Font = New-Object System.Drawing.Font(
    "Segoe UI",
    18,
    [System.Drawing.FontStyle]::Bold
)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(28,25)
$form.Controls.Add($title)

$versionLabel = New-Object System.Windows.Forms.Label
$versionLabel.Text = "Version $Version"
$versionLabel.ForeColor = [System.Drawing.Color]::FromArgb(165,165,175)
$versionLabel.Font = New-Object System.Drawing.Font("Segoe UI",9)
$versionLabel.AutoSize = $true
$versionLabel.Location = New-Object System.Drawing.Point(31,64)
$form.Controls.Add($versionLabel)

$status = New-Object System.Windows.Forms.Label
$status.Text = "Preparing..."
$status.ForeColor = [System.Drawing.Color]::FromArgb(225,225,230)
$status.Font = New-Object System.Drawing.Font("Segoe UI",10)
$status.Size = New-Object System.Drawing.Size(430,25)
$status.Location = New-Object System.Drawing.Point(30,104)
$form.Controls.Add($status)

$percent = New-Object System.Windows.Forms.Label
$percent.Text = "0%"
$percent.ForeColor = [System.Drawing.Color]::FromArgb(225,225,230)
$percent.TextAlign = "MiddleRight"
$percent.Size = New-Object System.Drawing.Size(55,25)
$percent.Location = New-Object System.Drawing.Point(455,104)
$form.Controls.Add($percent)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Minimum = 0
$progress.Maximum = 100
$progress.Value = 0
$progress.Style = "Continuous"
$progress.Size = New-Object System.Drawing.Size(480,24)
$progress.Location = New-Object System.Drawing.Point(30,137)
$form.Controls.Add($progress)

$note = New-Object System.Windows.Forms.Label
$note.Text = "Please keep this window open while AMF is being installed."
$note.ForeColor = [System.Drawing.Color]::FromArgb(130,130,140)
$note.AutoSize = $true
$note.Location = New-Object System.Drawing.Point(30,178)
$form.Controls.Add($note)

$form.Show()
[System.Windows.Forms.Application]::DoEvents()

try {
    Set-InstallProgress 6 "Checking the current installation..."

    if ($hasInstall) {
        Set-InstallProgress 12 "Closing the old AMF..."
        Stop-AMF
    }

    Set-InstallProgress 20 "Preparing the AMF folder..."
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

    # IMPORTANT: user state is intentionally NOT read, rewritten, or
    # copied during updates. config.json, cart.json, cart_backups, and any
    # other runtime state already live in the permanent AMF install folder.
    # Program-file updates leave those files byte-for-byte untouched.

    Set-InstallProgress 34 "Replacing AMF application files..."

    foreach ($file in @(
        "app.py",
        "amf_features.py",
        "verify_install.py",
        "start_amf.py",
        "provider_pages.py",
        "AMF.exe",
        "AMF.ico",
        "AMF.png",
        "requirements.txt",
        "launch_amf.ps1",
        "uninstall.ps1"
    )) {
        $source = Join-Path $PayloadDir $file

        if (-not (Test-Path $source)) {
            throw "Setup is missing required file: $file"
        }

        Copy-Item `
            -Path $source `
            -Destination (Join-Path $InstallDir $file) `
            -Force
    }

    Set-InstallProgress 48 "Locating the AMF runtime..."

    $python = Find-Python
    if (-not $python) {
        throw "Python could not be found on this computer."
    }

    # Resolve Windows execution aliases to the interpreter that passed verification.
    $resolvedPython = & $python -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0 -or -not $resolvedPython) { throw "Could not resolve the Python runtime." }
    $python = ([string]($resolvedPython | Select-Object -Last 1)).Trim()
    if (-not (Test-Path -LiteralPath $python)) { throw "Python runtime does not exist: $python" }
    $pythonw = Pythonw-For $python
    if (-not $pythonw) {
        throw "pythonw.exe could not be found beside: $python"
    }

    Set-Content `
        -Path (Join-Path $InstallDir "python_path.txt") `
        -Value $python `
        -Encoding ASCII

    Set-Content `
        -Path (Join-Path $InstallDir "pythonw_path.txt") `
        -Value $pythonw `
        -Encoding ASCII

    Set-InstallProgress 58 "Checking AMF components..."

    $dependencyLog = Join-Path $InstallDir "dependency-check.log"
    & $python -c "import PySide6, requests, qbittorrentapi, bs4" *> $dependencyLog

    if ($LASTEXITCODE -ne 0) {
        Set-InstallProgress 63 "Installing required AMF components..."

        & $python `
            -m pip install `
            -r (Join-Path $InstallDir "requirements.txt") `
            --disable-pip-version-check *>> $dependencyLog

        if ($LASTEXITCODE -ne 0) {
            $details = Get-Content -LiteralPath $dependencyLog -Raw -ErrorAction SilentlyContinue
            throw "Required Python components could not be installed.`r`n$details`r`nLog: $dependencyLog"
        }
    }

    Set-InstallProgress 70 "Verifying AMF startup and version..."

    $verifyLog = Join-Path $InstallDir "install-check.log"
    $verifyErrorLog = Join-Path $InstallDir "install-check-error.log"
    $verifyScript = Join-Path $InstallDir "verify_install.py"
    $check = Start-Process -FilePath $python -WindowStyle Hidden `
        -ArgumentList @('"' + $verifyScript + '"', $Version) `
        -WorkingDirectory $InstallDir -PassThru -Wait `
        -RedirectStandardOutput $verifyLog -RedirectStandardError $verifyErrorLog
    if ($check.ExitCode -ne 0) {
        $details = Get-Content -LiteralPath $verifyErrorLog -Raw -ErrorAction SilentlyContinue
        $output = Get-Content -LiteralPath $verifyLog -Raw -ErrorAction SilentlyContinue
        throw "AMF startup verification failed.`r`n$output`r`n$details`r`nLogs: $verifyLog and $verifyErrorLog"
    }

    Set-InstallProgress 73 "Registering AMF with Windows..."

    New-Item -Path $UninstallReg -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "DisplayName" `
        -Value "AMF" -PropertyType String -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "DisplayVersion" `
        -Value $Version -PropertyType String -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "Publisher" `
        -Value "AMF" -PropertyType String -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "InstallLocation" `
        -Value $InstallDir -PropertyType String -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "DisplayIcon" `
        -Value (Join-Path $InstallDir "AMF.ico") `
        -PropertyType String -Force | Out-Null

    $uninstallCommand = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' +
        (Join-Path $InstallDir "uninstall.ps1") +
        '"'
    )

    New-ItemProperty -Path $UninstallReg -Name "UninstallString" `
        -Value $uninstallCommand -PropertyType String -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "NoModify" `
        -Value 1 -PropertyType DWord -Force | Out-Null

    New-ItemProperty -Path $UninstallReg -Name "NoRepair" `
        -Value 1 -PropertyType DWord -Force | Out-Null

    Set-InstallProgress 82 "Refreshing AMF in Windows Search..."

    Remove-Item $StartLink -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $StartMenuDir "Anime Downloader.lnk") `
        -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $StartMenuDir "AnimeDownloader.lnk") `
        -Force -ErrorAction SilentlyContinue

    New-AMFShortcut `
        -ShortcutPath $StartLink `
        -PythonwPath $pythonw

    if (Test-Path $DesktopLink) {
        Remove-Item $DesktopLink -Force -ErrorAction SilentlyContinue
        New-AMFShortcut `
            -ShortcutPath $DesktopLink `
            -PythonwPath $pythonw
    }

    Set-InstallProgress 100 "AMF $Version installed successfully."
    Start-Sleep -Milliseconds 550
    $form.Close()

    $launch = [System.Windows.Forms.MessageBox]::Show(
        "AMF $Version was installed successfully.`r`n`r`nOpen AMF now?",
        "AMF Setup",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Information
    )

    if ($launch -eq [System.Windows.Forms.DialogResult]::Yes) {
        # SAME launch command as the Start-menu shortcut.
        Start-Process `
            -WindowStyle Normal `
            -FilePath $pythonw `
            -ArgumentList @('"' + (Join-Path $InstallDir "start_amf.py") + '"') `
            -WorkingDirectory $InstallDir
    }

    exit 0
}
catch {
    try { $form.Close() } catch {}

    [System.Windows.Forms.MessageBox]::Show(
        "AMF Setup could not complete the installation.`r`n`r`n" +
        $_.Exception.Message,
        "AMF Setup",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null

    exit 1
}
