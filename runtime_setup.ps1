# Private runtime: never invokes a Store alias or modifies the user's Python.
function Invoke-AMFProcess([string]$Executable, [string]$Arguments, [string]$LogPrefix) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput "$LogPrefix.log" -RedirectStandardError "$LogPrefix-error.log"
    if ($process.ExitCode -ne 0) {
        $details = (Get-Content "$LogPrefix-error.log" -Raw -ErrorAction SilentlyContinue)
        throw "Process failed (exit $($process.ExitCode)).`r`n$details`r`nFull logs: $LogPrefix.log and $LogPrefix-error.log"
    }
}

function Install-AMFRuntime([string]$Root, [string]$SetupRoot) {
    if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Build -lt 17763) {
        throw 'AMF requires 64-bit Windows 10 (1809 or later) or Windows 11.'
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $runtime = Join-Path $Root 'runtime-3.13.7'
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $python = Join-Path $runtime 'python.exe'
    if (-not (Test-Path (Join-Path $runtime 'runtime-ready.txt'))) {
        $archive = Join-Path $runtime 'python.zip'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.7/python-3.13.7-embed-amd64.zip' -OutFile $archive
        if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne 'F6CCA216A359BE84797CABB54149CE5E062AFB16CC7567EB7FC51CACB2D86B65') {
            throw 'The Python download failed its integrity check. Please run Setup again.'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
        Set-Content -LiteralPath (Join-Path $runtime 'python313._pth') -Encoding ASCII -Value "python313.zip`r`n.`r`nLib\site-packages`r`nimport site"
        Set-Content -LiteralPath (Join-Path $runtime 'runtime-ready.txt') -Value '3.13.7'
        Remove-Item -LiteralPath $archive -Force
    }
    $pip = Join-Path $SetupRoot 'pip.pyz'
    if ((Get-FileHash $pip -Algorithm SHA256).Hash -ne '91D5FD9F6F25549FD839C60536C6F1B945316CE3588D34A605635B6071C91526') { throw 'Setup pip.pyz is damaged. Download the complete setup folder again.' }
    $requirements = Join-Path $SetupRoot 'payload\requirements.txt'
    Invoke-AMFProcess $python ('"' + $pip + '" install --isolated --disable-pip-version-check --only-binary=:all: --upgrade --target "' + (Join-Path $runtime 'Lib\site-packages') + '" -r "' + $requirements + '"') (Join-Path $Root 'dependencies')
    return $python
}
