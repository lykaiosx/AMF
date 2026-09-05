Option Explicit
Dim shell, fso, installDir, pythonwFile, pythonwPath, appPath, file

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

installDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwFile = installDir & "\pythonw_path.txt"
appPath = installDir & "\app.py"
pythonwPath = ""

On Error Resume Next
If fso.FileExists(pythonwFile) Then
    Set file = fso.OpenTextFile(pythonwFile, 1, False)
    pythonwPath = Trim(file.ReadAll)
    file.Close
End If
On Error GoTo 0

If pythonwPath <> "" And fso.FileExists(pythonwPath) Then
    shell.Run """" & pythonwPath & """ """ & appPath & """", 0, False
    WScript.Quit 0
End If

shell.Run "pyw.exe -3 """ & appPath & """", 0, False
