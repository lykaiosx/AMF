$ErrorActionPreference = 'Stop'
$setup = Join-Path $PSScriptRoot 'Setup.exe'
if (-not (Test-Path -LiteralPath $setup)) {
    throw 'Download AMF-4.11-Setup.exe from https://github.com/lykaiosx/AMF/releases/tag/v4.11. The source folder is not the installer.'
}
Start-Process -FilePath $setup -WindowStyle Normal -Wait
