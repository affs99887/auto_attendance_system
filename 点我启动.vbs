Option Explicit

Dim shell, fso, rootDir, exePath, workDir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

rootDir = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = fso.BuildPath(rootDir, "release\win-unpacked\AutoAttendance.exe")
workDir = fso.GetParentFolderName(exePath)

If fso.FileExists(exePath) Then
  shell.CurrentDirectory = workDir
  shell.Run Chr(34) & exePath & Chr(34), 1, False
  WScript.Quit 0
End If

MsgBox "Portable AAS build not found:" & vbCrLf & exePath & vbCrLf & vbCrLf & _
       "Build it first with: npm run dist:dir", vbExclamation, "AAS Launcher"
WScript.Quit 1
