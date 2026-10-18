param(
    [ValidateSet('tiny.en', 'base.en')]
    [string]$Model = 'tiny.en'
)

$ErrorActionPreference = 'Stop'

$dest = Join-Path $PSScriptRoot "..\models\faster-whisper-$Model"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$base = "https://hf-mirror.com/Systran/faster-whisper-$Model/resolve/main"

foreach ($file in @('config.json', 'tokenizer.json', 'vocabulary.txt', 'model.bin')) {
    $target = Join-Path $dest $file
    if ((Test-Path $target) -and (Get-Item $target).Length -gt 0) {
        Write-Host "skip $file"
        continue
    }
    Write-Host "downloading $file ..."
    curl.exe -L --retry 3 --retry-delay 2 --max-time 900 -o $target "$base/$file"
    if ($LASTEXITCODE -ne 0) {
        throw "download failed: $file"
    }
}

Get-ChildItem $dest | Select-Object Name, Length
