Option Explicit
Dim shell, fso, setupDir, installerFile, command, result

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

setupDir = fso.GetParentFolderName(WScript.ScriptFullName)
installerFile = setupDir & "\installer.ps1"

If Not fso.FileExists(installerFile) Then
    MsgBox "AMF Setup is missing installer.ps1.", vbCritical, "AMF Setup"
    WScript.Quit 1
End If

command = "powershell.exe -NoProfile -STA -ExecutionPolicy Bypass " & _
          "-WindowStyle Hidden -File """ & installerFile & """"

result = shell.Run(command, 0, True)
WScript.Quit result
