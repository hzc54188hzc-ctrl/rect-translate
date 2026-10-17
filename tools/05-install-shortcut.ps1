# Install a desktop shortcut and a startup entry (self-use script form, no exe packaging).
# ASCII-only on purpose: PowerShell 5.1 reads .ps1 without BOM as ANSI and would garble
# any non-ASCII literal. The Chinese shortcut name is built from code points instead.
# Usage: powershell -NoProfile -File tools\05-install-shortcut.ps1 [-NoAutostart]

param([switch]$NoAutostart)

$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$exe = Join-Path $app '.venv\Scripts\pythonw.exe'
$scriptFile = Join-Path $app '01-run.py'
$icon = Join-Path $app 'app.ico'

foreach ($path in $exe, $scriptFile) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing file: $path" }
}
if (-not (Test-Path -LiteralPath $icon)) { throw "Missing icon: $icon (run tools\make_icon.py first)" }

$name = [string]::Join('', [char[]]@(0x77E9, 0x5F62, 0x7FFB, 0x8BD1))
$shell = New-Object -ComObject WScript.Shell

function New-Shortcut([string]$linkPath) {
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath = $exe
    $link.Arguments = '"{0}"' -f $scriptFile
    $link.WorkingDirectory = $app
    $link.IconLocation = '{0},0' -f $icon
    $link.Description = 'Rectangle translator'
    $link.Save()
    $check = $shell.CreateShortcut($linkPath)
    "{0}`n  target={1}`n  args={2}`n  icon={3}" -f $linkPath, $check.TargetPath, $check.Arguments, $check.IconLocation
}

$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) ($name + '.lnk')
'Desktop shortcut:'
New-Shortcut $desktop

if (-not $NoAutostart) {
    $startup = Join-Path ([Environment]::GetFolderPath('Startup')) ($name + '.lnk')
    'Startup entry:'
    New-Shortcut $startup
}

'Done. Delete the .lnk files listed above to undo.'
