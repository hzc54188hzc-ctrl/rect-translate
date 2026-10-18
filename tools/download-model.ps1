param(
    [ValidateSet('tiny.en', 'base.en')]
    [string]$Model = 'tiny.en'
)

$ErrorActionPreference = 'Stop'

$dest = Join-Path $PSScriptRoot "..\models\faster-whisper-$Model"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$base = "https://hf-mirror.com/Systran/faster-whisper-$Model/resolve/main"
$expected = @{ 'model.bin' = 75537502 }

foreach ($file in @('config.json', 'tokenizer.json', 'vocabulary.txt', 'model.bin')) {
    $target = Join-Path $dest $file
    if (Test-Path $target) {
        $size = (Get-Item $target).Length
        $want = $expected[$file]
        if ($want -and $size -eq $want) {
            Write-Host "skip $file"
            continue
        }
        if (-not $want -and $size -gt 0) {
            Write-Host "skip $file"
            continue
        }
    }
    Write-Host "downloading $file (resume if partial) ..."
    curl.exe -L --retry 3 --retry-delay 2 -C - --max-time 900 -o $target "$base/$file"
    if ($LASTEXITCODE -ne 0) {
        # 416 = 文件其实已完整，交给下一轮大小检查
        if ($LASTEXITCODE -ne 33 -and $LASTEXITCODE -ne 22) {
            throw "download failed: $file"
        }
    }
}

Get-ChildItem $dest | Select-Object Name, Length
