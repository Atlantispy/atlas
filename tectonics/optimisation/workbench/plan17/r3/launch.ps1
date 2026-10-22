param(
    [Parameter(Mandatory=$true)][ValidateSet('controls','q23','q24','repeats23','repeats24')][string]$Phase,
    [Parameter(Mandatory=$true)][string]$ManifestSha256
)
$ErrorActionPreference='Stop'
$taskPython='C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe'
$taskRunq='C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/q/runq.py'
$taskManifest=Join-Path $PSScriptRoot 'REQUEST-r3.json'
if ((Get-FileHash -LiteralPath $taskManifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ManifestSha256) {
    throw 'Request identity changed'
}
# Process environment only. The seed is set before queue and dispatcher creation.
$taskSaved=@{}
$taskNames=@(Get-ChildItem Env: | Where-Object {$_.Name -like 'PYTHON*'} | ForEach-Object {$_.Name})
foreach($taskName in @($taskNames + 'PYTHONHASHSEED' + 'PYTHONDONTWRITEBYTECODE' | Select-Object -Unique)) {
    $taskSaved[$taskName]=[Environment]::GetEnvironmentVariable($taskName,'Process')
    [Environment]::SetEnvironmentVariable($taskName,$null,'Process')
}
try {
    $env:PYTHONHASHSEED='0'
    $env:PYTHONDONTWRITEBYTECODE='1'
    $taskCommand=@($taskPython,'-B','-s','-P',(Join-Path $PSScriptRoot 'run_plan17.py'),
                   '--manifest',$taskManifest,'--sha256',$ManifestSha256,'--phase',$Phase)
    if($Phase -in @('q23','q24')) {
        & $taskPython -B -I $taskRunq run $Phase -- @taskCommand
    } else {
        & $taskPython -B -I $taskRunq small --cores 1 --gib 1 -- @taskCommand
    }
    $taskExit=$LASTEXITCODE
} finally {
    foreach($taskName in $taskSaved.Keys) {
        [Environment]::SetEnvironmentVariable($taskName,$taskSaved[$taskName],'Process')
    }
}
if($taskExit -ne 0) { throw "Plan17 phase exit $taskExit; preserve evidence; no automatic retry" }
