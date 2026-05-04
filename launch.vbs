' Launches the Vendor Pricing Tracker silently (no black terminal window)
Set objShell = CreateObject("WScript.Shell")
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = strDir
objShell.Run "pythonw app_desktop.py", 0, False
