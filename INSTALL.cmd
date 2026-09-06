@echo off
cd /d "%~dp0"
if exist "Setup.exe" (
    start "" "Setup.exe"
) else (
    echo Download AMF-4.11-Setup.exe from the GitHub release:
    echo https://github.com/lykaiosx/AMF/releases/tag/v4.11
    pause
)
