$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & "$PSScriptRoot\runtime\python\python.exe" -m autoflow editor
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
