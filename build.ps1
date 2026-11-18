param([string]$Python = "$PSScriptRoot\.venv-build\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
$buildPython = (Resolve-Path -LiteralPath $Python).Path
$originalPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    & $buildPython -m PyInstaller --noconfirm --clean --distpath "$PSScriptRoot\dist" --workpath "$PSScriptRoot\build" "$PSScriptRoot\OrbitPet.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
}
finally {
    $env:PATH = $originalPath
}
