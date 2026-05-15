# Sprint 23 T4 — full v1.10.1 eval matrix (7 langs × 3 modes = 21 cells)
# Sequential: hybrid → hybrid_rerank (reuses hybrid cache) → vector_only (forces reindex)

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Practicas\Desktop\Proyecto CONTEXT\code-context"

$cache = "$env:TEMP\cc-sprint23-eval-matrix"
$env:CC_CACHE_DIR = $cache

Write-Host ""
Write-Host "=== Pass 1: hybrid (sqlite + rerank=off) ==="
Write-Host ""
$env:CC_KEYWORD_INDEX = "sqlite"
$env:CC_RERANK        = "off"
$t1 = Get-Date
& .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --config benchmarks\eval\configs\multi.yaml `
    --output-dir benchmarks\eval\results\v1.10.1\hybrid\
$t1d = (Get-Date) - $t1
Write-Host ""
Write-Host "Pass 1 wall: $($t1d.TotalSeconds) s"
Write-Host ""

Write-Host ""
Write-Host "=== Pass 2: hybrid_rerank (sqlite + rerank=on) ==="
Write-Host ""
$env:CC_KEYWORD_INDEX = "sqlite"
$env:CC_RERANK        = "on"
$t2 = Get-Date
& .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --config benchmarks\eval\configs\multi.yaml `
    --output-dir benchmarks\eval\results\v1.10.1\hybrid_rerank\
$t2d = (Get-Date) - $t2
Write-Host ""
Write-Host "Pass 2 wall: $($t2d.TotalSeconds) s"
Write-Host ""

Write-Host ""
Write-Host "=== Pass 3: vector_only (none + rerank=off) ==="
Write-Host ""
$env:CC_KEYWORD_INDEX = "none"
$env:CC_RERANK        = "off"
$t3 = Get-Date
& .\.venv\Scripts\python.exe -m benchmarks.eval.runner `
    --config benchmarks\eval\configs\multi.yaml `
    --output-dir benchmarks\eval\results\v1.10.1\vector_only\
$t3d = (Get-Date) - $t3
Write-Host ""
Write-Host "Pass 3 wall: $($t3d.TotalSeconds) s"
Write-Host ""

$total = $t1d.TotalSeconds + $t2d.TotalSeconds + $t3d.TotalSeconds
Write-Host "=== Matrix complete. Total wall: $total s ($($total/60) min) ==="
