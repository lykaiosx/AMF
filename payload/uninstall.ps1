Add-Type -AssemblyName System.Windows.Forms

$installDir = Join-Path $env:LOCALAPPDATA "Programs\AMF"
$startLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\AMF.lnk"
$desktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "AMF.lnk"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AMF"
$appPathKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\AMF.exe"

$answer = [System.Windows.Forms.MessageBox]::Show(
    "Uninstall AMF?",
    "AMF",
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }

Remove-Item $startLink -Force -ErrorAction SilentlyContinue
Remove-Item $desktopLink -Force -ErrorAction SilentlyContinue
Remove-Item $uninstallKey -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $appPathKey -Recurse -Force -ErrorAction SilentlyContinue

$escaped = $installDir.Replace('"','""')
Start-Process -FilePath "cmd.exe" -WindowStyle Hidden -ArgumentList @(
    "/c",
    "ping 127.0.0.1 -n 2 >nul & rmdir /s /q `"$escaped`""
)

[System.Windows.Forms.MessageBox]::Show(
    "AMF was uninstalled.",
    "AMF",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
