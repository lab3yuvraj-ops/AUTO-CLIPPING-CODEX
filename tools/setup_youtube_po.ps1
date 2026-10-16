param([string]$Python = '', [string]$CaFile = '')
$ErrorActionPreference = 'Stop'
$clipRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) { $Python = Join-Path $clipRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Supply -Python with the active project Python executable.' }
if ($CaFile) {
    $clipCa = (Resolve-Path -LiteralPath $CaFile).Path
    $env:PIP_CERT = $clipCa
    $env:NODE_EXTRA_CA_CERTS = $clipCa
}
$clipVersion = & node --version
if ($LASTEXITCODE -ne 0 -or [int]($clipVersion.TrimStart('v').Split('.')[0]) -lt 22) { throw 'Node.js >=22 is required.' }
$clipProvider = Join-Path $clipRoot 'workflow/vendor/bgutil-ytdlp-pot-provider-2.0.2'
if (-not (Test-Path -LiteralPath $clipProvider)) {
    & git clone --depth 1 --branch 2.0.2 --single-branch https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git $clipProvider
    if ($LASTEXITCODE -ne 0) { throw 'Provider checkout failed.' }
}
$clipOrigin = & git -C $clipProvider remote get-url origin
$clipTag = & git -C $clipProvider describe --tags --exact-match
if ($clipOrigin -ne 'https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git' -or $clipTag -ne '2.0.2') { throw 'Existing provider checkout is not the expected official release; it was preserved.' }
& $Python -m pip --cache-dir (Join-Path $clipRoot 'workflow/install-cache') install --disable-pip-version-check --retries 0 -r (Join-Path $clipRoot 'requirements-youtube-po-token.txt')
if ($LASTEXITCODE -ne 0) { throw 'Optional plugin installation failed; TLS checking remains enabled.' }
Push-Location (Join-Path $clipProvider 'server')
try {
    & npm.cmd ci --no-audit --no-fund --maxsockets=3 --fetch-retries=1 --fetch-timeout=30000
    if ($LASTEXITCODE -ne 0) { throw 'Provider dependency installation failed.' }
    & npx.cmd --no-install tsc
    if ($LASTEXITCODE -ne 0) { throw 'Provider compilation failed.' }
    & node build/generate_once.js --version
    if ($LASTEXITCODE -ne 0) { throw 'Offline provider check failed.' }
} finally { Pop-Location }
& $Python (Join-Path $clipRoot 'reel.py') cleanup-install-cache
if ($LASTEXITCODE -ne 0) { throw 'Provider installed; private pip-cache cleanup needs attention.' }
Write-Output 'Installed optional local provider. No tokens generated or YouTube downloads started.'
Write-Output ('Add to private .env: YOUTUBE_PO_TOKEN_HOME=' + (Join-Path $clipProvider 'server').Replace('\','/'))
