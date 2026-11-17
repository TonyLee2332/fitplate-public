param(
    [switch]$SetupOnly,
    [switch]$CheckOnly,
    [ValidateRange(1024, 65535)][int]$Port = 8519,
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$fitPlateRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $fitPlateRoot
$fitPlateEnv = Join-Path $fitPlateRoot '.venv'
$fitPlatePython = Join-Path $fitPlateEnv 'Scripts\python.exe'
$fitPlateStamp = Join-Path $fitPlateEnv '.fitplate-environment.json'
$fitPlateRequirements = Join-Path $fitPlateRoot 'requirements.txt'

function Get-PythonInfo {
    param([string]$Executable, [string[]]$PrefixArguments = @())
    try {
        $probe = "import json,os,sys; print(json.dumps(dict(version=list(sys.version_info[:3]),prefix=os.path.realpath(sys.prefix),base=os.path.join(sys.base_prefix,'python.exe'))))"
        $output = @(& $Executable @PrefixArguments -c $probe 2>$null)
        if ($LASTEXITCODE -ne 0) { return $null }
        $info = ($output -join "`n") | ConvertFrom-Json
        if ($info.version[0] -ne 3 -or $info.version[1] -lt 12) { return $null }
        return $info
    } catch { return $null }
}

function Find-BasePython {
    if ($PythonPath) {
        $info = Get-PythonInfo -Executable $PythonPath
        if ($info -and (Test-Path -LiteralPath $info.base)) { return $info }
        throw 'The specified Python cannot run. Use an installed Python 3.12 or newer.'
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.12', '-3.13', '-3')) {
            $info = Get-PythonInfo -Executable $launcher.Source -PrefixArguments @($version)
            if ($info -and (Test-Path -LiteralPath $info.base)) { return $info }
        }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) {
        $info = Get-PythonInfo -Executable $command.Source
        if ($info -and (Test-Path -LiteralPath $info.base)) { return $info }
    }
    throw 'Python 3.12 or newer was not found. Install Python, then double-click Start FitPlate.cmd again. Python 3.12 or 3.13 is recommended.'
}

function Backup-OldEnvironment {
    if (-not (Test-Path -LiteralPath $fitPlateEnv)) { return }
    $item = Get-Item -LiteralPath $fitPlateEnv -Force
    if ($item.Parent.FullName -ne $fitPlateRoot -or $item.Name -ne '.venv' -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw 'The environment is outside this project or is a linked folder. Move it manually before retrying.'
    }
    $backup = '.venv.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    try {
        Rename-Item -LiteralPath $item.FullName -NewName $backup
    } catch {
        throw 'The old environment could not be moved. Close FitPlate and other programs using this project, then retry.'
    }
    Write-Host "Previous environment preserved as $backup."
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $fitPlateRoot 'app.py')) -or
        -not (Test-Path -LiteralPath $fitPlateRequirements)) {
        throw 'Required project files are missing. Extract the entire FitPlate folder before starting it.'
    }
    $requirementsHash = (Get-FileHash -LiteralPath $fitPlateRequirements -Algorithm SHA256).Hash
    $metadata = $null
    if (Test-Path -LiteralPath $fitPlateStamp) {
        try { $metadata = Get-Content -LiteralPath $fitPlateStamp -Raw | ConvertFrom-Json } catch {}
    }
    $info = $null
    if (Test-Path -LiteralPath $fitPlatePython) { $info = Get-PythonInfo -Executable $fitPlatePython }
    $belongsHere = $false
    if ($info -and $info.prefix -eq $fitPlateEnv) {
        if ($metadata) {
            $belongsHere = $metadata.project -eq $fitPlateRoot -and $metadata.computer -eq $env:COMPUTERNAME
        } else {
            $configPath = Join-Path $fitPlateEnv 'pyvenv.cfg'
            if (Test-Path -LiteralPath $configPath) {
                $config = Get-Content -LiteralPath $configPath -Raw
                $belongsHere = $config.IndexOf($fitPlateEnv, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
        }
    }
    if (-not $belongsHere) {
        if ($CheckOnly) { throw 'The local Python environment is missing, moved, or incompatible. Run Start FitPlate.cmd to rebuild it.' }
        $baseInfo = Find-BasePython
        Write-Host ('Creating a local environment with Python ' + ($baseInfo.version -join '.') + '...')
        Backup-OldEnvironment
        & $baseInfo.base -m venv $fitPlateEnv
        if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed. Check Python installation and folder write permissions.' }
        $metadata = $null
    }
    $importsReady = $false
    try {
        & $fitPlatePython -c 'import streamlit,mutagen,PIL,sqlite3,numpy,ingredient_parser,torch,transformers' 2>$null
        $importsReady = $LASTEXITCODE -eq 0
    } catch {}
    $needsInstall = -not $importsReady -or -not $metadata -or $metadata.requirements -ne $requirementsHash
    if ($CheckOnly -and $needsInstall) { throw 'Dependencies or environment metadata need updating. Run Start FitPlate.cmd.' }
    if ($needsInstall) {
        Write-Host 'Installing project dependencies. Internet access is required for the first setup...'
        & $fitPlatePython -m pip install --disable-pip-version-check -r $fitPlateRequirements
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your connection and the pip error above, then retry.' }
        & $fitPlatePython -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed. Review the package error above.' }
        $stamp = @{project=$fitPlateRoot; computer=$env:COMPUTERNAME; requirements=$requirementsHash}
        $stamp | ConvertTo-Json | Set-Content -LiteralPath $fitPlateStamp -Encoding UTF8
    }
    if (-not $CheckOnly) {
        & $fitPlatePython -m fitplate.install_depth
        if ($LASTEXITCODE -ne 0) { throw 'Depth model setup failed. Check the connection and model files before retrying.' }
    }
    Write-Host 'FitPlate environment is ready.'
    if ($SetupOnly -or $CheckOnly) { exit 0 }
    Write-Host "Open http://localhost:$Port"
    & $fitPlatePython -m streamlit run (Join-Path $fitPlateRoot 'app.py') --server.address 127.0.0.1 --server.port $Port
    exit $LASTEXITCODE
} catch {
    Write-Host ''
    Write-Host ('FitPlate could not start: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

