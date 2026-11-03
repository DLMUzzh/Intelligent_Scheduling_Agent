param(
    [switch]$Reload,
    [switch]$NoInstall,
    [ValidateRange(0, 65535)][int]$Port = 0
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv --python 3.12 .venv
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } else {
        throw 'Install Python 3.12 or uv, then run this script again.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create virtual environment.' }
}
if (-not $NoInstall) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv pip install --python $pythonPath -r requirements.lock
    } else {
        & $pythonPath -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw 'Failed to initialize pip.' }
        & $pythonPath -m pip install -r requirements.lock
    }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python dependencies.' }

    $npmCommand = Get-Command npm.cmd -ErrorAction Stop
    $npmCliPath = Join-Path (Split-Path -Parent $npmCommand.Source) 'node_modules\npm\bin\npm-cli.js'
    if (-not (Test-Path -LiteralPath $npmCliPath)) { throw 'Cannot locate the npm CLI.' }
    $nodePath = Join-Path $PSScriptRoot '.runtime\node_modules\node\bin\node.exe'
    if (-not (Test-Path -LiteralPath $nodePath)) {
        $systemNode = Get-Command node -ErrorAction SilentlyContinue
        $systemVersion = if ($systemNode) { & $systemNode.Source --version } else { '' }
        if ($systemVersion -match '^v24\.') {
            $nodePath = $systemNode.Source
        } else {
            $runtimeDirectory = Join-Path $PSScriptRoot '.runtime'
            New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
            Push-Location -LiteralPath $runtimeDirectory
            try {
                & $npmCommand.Source install --no-package-lock --no-save node@24
                if ($LASTEXITCODE -ne 0) { throw 'Failed to install the project-local Node.js 24 runtime.' }
            } finally {
                Pop-Location
            }
        }
    }
    $nodeVersion = & $nodePath --version
    if ($nodeVersion -notmatch '^v24\.') { throw 'Frontend build requires Node.js 24.' }
    $env:PATH = (Split-Path -Parent $nodePath) + ';' + $env:PATH
    Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
    try {
        & $nodePath $npmCliPath ci
        if ($LASTEXITCODE -ne 0) { throw 'Failed to install frontend dependencies.' }
        & $nodePath $npmCliPath run build
        if ($LASTEXITCODE -ne 0) { throw 'Failed to build frontend.' }
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) {
    throw 'Frontend build is missing. Run start.ps1 without -NoInstall.'
}
if ($Port -gt 0) { $env:FLEET_PORT = "$Port" }
$serverConfig = & $pythonPath -c 'import json; from app.core.runtime import runtime_settings as c; print(json.dumps(dict(host=c.host, port=c.port)))'
if ($LASTEXITCODE -ne 0) { throw 'Failed to load runtime configuration.' }
$serverConfig = $serverConfig | ConvertFrom-Json
$serverArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$($serverConfig.port)", '--no-proxy-headers')
if ($Reload) { $serverArgs += '--reload' }
Write-Host "Fleetwise: http://127.0.0.1:$($serverConfig.port)"
& $pythonPath @serverArgs
exit $LASTEXITCODE
