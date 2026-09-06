param([Parameter(Mandatory=$true)][string]$Compiler,
      [string]$BuildDirectory = (Join-Path $env:TEMP 'AMF-build'))
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'runtime_setup.ps1')
$python = Install-AMFRuntime $BuildDirectory $PSScriptRoot
Invoke-AMFProcess $python ('"' + (Join-Path $PSScriptRoot 'payload\verify_install.py') + '" 4.13') (Join-Path $BuildDirectory 'verify')
& $Compiler ('/DRuntimeDir=' + (Split-Path $python -Parent)) (Join-Path $PSScriptRoot 'AMF.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dist\AMF-4.13-Setup.exe') -Destination (Join-Path $PSScriptRoot 'Setup.exe') -Force

