# The PC's side of tools/modswitch/install.sh: copies Switch-Ff6Mod.ps1 to %LOCALAPPDATA%\ff6pr-mods
# and makes "FINAL FANTASY VI - Worlds Collide" / "- Brave New World" / "- Beyond Chaos" / "- T-Edition"
# shortcuts on the Desktop and in the Start menu, each making that mod the active one and starting FF6
# through Steam.
param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$GameExe)
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'ff6pr-mods'
New-Item -ItemType Directory -Force $dir | Out-Null
$script = Join-Path $dir 'Switch-Ff6Mod.ps1'
Copy-Item $Source $script -Force
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shell = New-Object -ComObject WScript.Shell
$tiles = @(@('wc', 'FINAL FANTASY VI - Worlds Collide'), @('bnw', 'FINAL FANTASY VI - Brave New World'),
           @('bc', 'FINAL FANTASY VI - Beyond Chaos'), @('ted', 'FINAL FANTASY VI - T-Edition'))
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  foreach ($t in $tiles) {
    $path = Join-Path $folder "$($t[1]).lnk"
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $ps
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Mod $($t[0]) -Launch"
    $lnk.WorkingDirectory = $dir
    $lnk.IconLocation = "$GameExe,0"
    $lnk.WindowStyle = 7
    $lnk.Description = "Make $($t[1].Substring(19)) FF6's active mod and start the game"
    $lnk.Save()
    Write-Output "[modswitch] PC: $path"
  }
}
