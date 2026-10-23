' FloatDock silent launcher - runs floatdock.pyw via pythonw with no console window.
' Double-click to start; safe to call from shortcuts or startup folder.
Option Explicit

Dim fso, sh, appDir, pyw, candidates, p
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = appDir

candidates = Array( _
    "pythonw.exe", _
    sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe", _
    sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\pythonw.exe", _
    sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\workbuddy\binaries\python\versions\3.13.12\pythonw.exe" _
)

pyw = ""
For Each p In candidates
    If InStr(p, "\") = 0 Or fso.FileExists(p) Then
        pyw = p
        Exit For
    End If
Next

If pyw <> "" Then
    sh.Run """" & pyw & """ """ & appDir & "\floatdock.pyw""", 0, False
End If
