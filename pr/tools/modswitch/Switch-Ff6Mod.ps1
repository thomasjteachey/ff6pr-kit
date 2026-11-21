<#
Switch FINAL FANTASY VI PR between the project's mods, all installed, one active: Worlds Collide,
Brave New World, Beyond Chaos, T-Edition. The PC's side of tools/modswitch (ff6-mod-switch.sh is the
Deck's). install.sh copies it to %LOCALAPPDATA%\ff6pr-mods and makes the Desktop and Start menu shortcuts
"FINAL FANTASY VI - Worlds Collide", "... - Brave New World", "... - Beyond Chaos" and "... - T-Edition",
which run it with -Launch.

  Switch-Ff6Mod.ps1 -Mod wc|bnw|bc|ted [-Launch] [-DryRun]   make that mod the active one (then start FF6
                                                             through Steam; -DryRun: only say what would move)
  Switch-Ff6Mod.ps1 -Mod status                              print the active mod and the shelved ones

A mod is BepInEx\plugins\<Mod> plus FINAL FANTASY VI_Data\StreamingAssets\Magicite\<Mod> (T-Edition only
the Magicite folder until its plugin exists); the inactive ones wait in BepInEx\mod-shelf\<Mod> and
BepInEx\mod-shelf\magicite\<Mod>, where nothing loads them (the shelf pr/tools/deploy.sh uses). Only
folders move; nothing is deleted, and saves are untouched (each mod has its own save files). Nothing
moves while the game is running, or while the PC test runner has Beyond Chaos installed for a test
(tools/bc_testinstall.py: BepInEx\bc_testinstall.json). Beyond Chaos and T-Edition switch in only
once they have a player build (the file it writes last: BepInEx\BeyondChaos\generator\bundle.json,
BepInEx\TEdition\build.json; the same rule as tools/deck_push.sh): before that, their copies here are
the PC test runner's test installs, which must not stay active.
#>
param([Parameter(Mandatory)][string]$Mod, [switch]$Launch, [switch]$DryRun, [string]$Game)
$ErrorActionPreference = 'Stop'
$AppId = 1173820
$Mods = @('WorldsCollide', 'BraveNewWorld', 'BeyondChaos', 'TEdition')
$state = Join-Path $env:LOCALAPPDATA 'ff6pr-mods'
New-Item -ItemType Directory -Force $state | Out-Null
function Write-SwitchLog([string]$msg) {
  if (-not $DryRun) { Add-Content -Encoding utf8 (Join-Path $state 'switch.log') "$(Get-Date -Format s) $msg" }
  Write-Output $msg
}
function Find-Game {
  $steam = (Get-ItemProperty HKCU:\Software\Valve\Steam -ErrorAction SilentlyContinue).SteamPath
  $libs = @()
  if ($steam) {
    $libs += $steam
    $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
      foreach ($m in [regex]::Matches((Get-Content -Raw $vdf), '"path"\s+"([^"]+)"')) { $libs += $m.Groups[1].Value -replace '\\\\', '\' }
    }
  }
  foreach ($l in $libs) {
    $g = Join-Path $l 'steamapps\common\FINAL FANTASY VI PR'
    if (Test-Path (Join-Path $g 'BepInEx')) { return $g }
  }
}
if (-not $Game) { $Game = Find-Game }
if (-not $Game) { Write-SwitchLog 'FINAL FANTASY VI PR with BepInEx not found'; exit 1 }

$P = Join-Path $Game 'BepInEx\plugins'
$S = Join-Path $Game 'BepInEx\mod-shelf'
$SM = Join-Path $S 'magicite'
$M = Join-Path $Game 'FINAL FANTASY VI_Data\StreamingAssets\Magicite'
function Test-Active([string]$which) { (Test-Path (Join-Path $P $which)) -or (Test-Path (Join-Path $M $which)) }
$active = @($Mods | Where-Object { Test-Active $_ })
$shelved = @($Mods | Where-Object { -not (Test-Active $_) -and ((Test-Path (Join-Path $S $_)) -or (Test-Path (Join-Path $SM $_))) })

switch -Regex ($Mod) {
  '^(wc|WorldsCollide)$' { $name = 'WorldsCollide' }
  '^(bnw|BraveNewWorld)$' { $name = 'BraveNewWorld' }
  '^(bc|BeyondChaos)$' { $name = 'BeyondChaos' }
  '^(ted|TEdition)$' { $name = 'TEdition' }
  '^status$' { Write-Output "active: $($active -join ' '); shelved: $($shelved -join ' ')"; exit 0 }
  default { Write-Output 'usage: Switch-Ff6Mod.ps1 -Mod wc|bnw|bc|ted|status [-Launch] [-DryRun]'; exit 1 }
}
if ($DryRun) { $Launch = $false }

function Move-Folder([string]$from, [string]$to) {
  if ($DryRun) { Write-Output "  would move $from -> $to"; return }
  if (Test-Path $to) { Remove-Item -Recurse -Force $to }
  New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
  Move-Item $from $to
}
$has = { param($a, $b) (Test-Path $a) -or (Test-Path $b) }
# installed (active or shelved): its Magicite folder, and its plugin folder unless it has none yet (T-Edition)
$installed = (& $has (Join-Path $M $name) (Join-Path $SM $name)) -and
             ($name -eq 'TEdition' -or (& $has (Join-Path $P $name) (Join-Path $S $name)))
# a player build, not a test install (see the header)
$ready = switch ($name) {
  'BeyondChaos' { Test-Path (Join-Path $Game 'BepInEx\BeyondChaos\generator\bundle.json') }
  'TEdition' { Test-Path (Join-Path $Game 'BepInEx\TEdition\build.json') }
  default { $true }
}
if (Get-Process -Name 'FINAL FANTASY VI' -ErrorAction SilentlyContinue) {
  Write-SwitchLog "the game is running ($($active -join ' ') active): nothing moved"
} elseif (Test-Path (Join-Path $Game 'BepInEx\bc_testinstall.json')) {
  Write-SwitchLog "Beyond Chaos is installed for a test (tools/bc_testinstall.py restore ends it): nothing moved"
  $Launch = $false
} elseif (-not $ready) {
  $what = if ($installed) { "what's here is the test runner's test copy" } else { "and none is installed here" }
  Write-SwitchLog "$name has no player build yet ($what): nothing moved"
  $Launch = $false
} elseif (-not $installed) {
  Write-SwitchLog "$name isn't installed here (pr/tools/deploy.sh puts it in): nothing moved"
  $Launch = $false
} else {
  foreach ($o in $Mods) {
    if ($o -eq $name) { continue }
    if (Test-Path (Join-Path $P $o)) { Move-Folder (Join-Path $P $o) (Join-Path $S $o) }
    if (Test-Path (Join-Path $M $o)) { Move-Folder (Join-Path $M $o) (Join-Path $SM $o) }
  }
  if (-not (Test-Path (Join-Path $P $name)) -and (Test-Path (Join-Path $S $name))) { Move-Folder (Join-Path $S $name) (Join-Path $P $name) }
  if (-not (Test-Path (Join-Path $M $name))) { Move-Folder (Join-Path $SM $name) (Join-Path $M $name) }
  if ($DryRun) { Write-Output "dry run: $name would be active, the others on the shelf; nothing moved" }
  else { Write-SwitchLog "$name active (the others on the shelf)" }
}
if ($Launch) { Start-Process "steam://rungameid/$AppId" }
