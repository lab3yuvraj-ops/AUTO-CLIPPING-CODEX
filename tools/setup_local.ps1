param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$setupRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$setupVenvPython = Join-Path $setupRoot '.venv/Scripts/python.exe'
Push-Location $setupRoot
try {
    if (-not (Test-Path -LiteralPath $setupVenvPython)) {
        if ($Python) { & $Python -m venv .venv } else { & py -3.11 -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 environment creation failed.' }
    }
    & $setupVenvPython -c 'import sys; assert sys.version_info[:2] == (3, 11), "Use Python 3.11"'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required; existing environment was preserved.' }
    $setupPipCache = Join-Path $setupRoot 'workflow/install-cache'
    # Only this checkout owns this pip cache. Never purge the global pip cache.
    & $setupVenvPython -m pip --cache-dir $setupPipCache install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip setup failed; installation cache retained.' }
    & $setupVenvPython -m pip --cache-dir $setupPipCache install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch install failed; installation cache retained.' }
    & $setupVenvPython -m pip --cache-dir $setupPipCache install -r requirements-local.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed; installation cache retained.' }
    & $setupVenvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed; installation cache retained.' }
    & $setupVenvPython -c 'import torch, torchaudio, faster_whisper, pyannote.audio, cv2; assert torch.version.cuda is None, "CPU-only PyTorch required"'
    if ($LASTEXITCODE -ne 0) { throw 'Local import/CPU check failed; installation cache retained.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    & $setupVenvPython reel.py cleanup-install-cache
    if ($LASTEXITCODE -ne 0) { throw 'Dependencies installed, but private installation-cache cleanup needs attention.' }
    Write-Output 'Python dependencies ready; project pip cache removed. Continue onboarding for system-tool checks, accounts and model downloads. No models, credentials or global pip cache were deleted.'
} finally { Pop-Location }
