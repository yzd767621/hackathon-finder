# Creates a "Hackathon Finder" icon on the desktop. Clicking it refreshes the list and opens it.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = Join-Path (Split-Path (& python -c "import sys;print(sys.executable)")) "pythonw.exe"
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Hackathon Finder.lnk"

$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath       = $py
$s.Arguments        = "`"$dir\hackathon_notifier.py`" --open"
$s.WorkingDirectory = $dir
$s.IconLocation     = "$env:SystemRoot\System32\shell32.dll,43"   # star icon
$s.Description      = "Find free, student-friendly hackathons (online or KL)"
$s.Save()
Write-Host "Created $lnk"
