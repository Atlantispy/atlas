param(
    [Parameter(Mandatory=$true)][ValidateSet('controls','q23','q24','repeats23','repeats24')][string]$Phase,
    [Parameter(Mandatory=$true)][string]$ManifestSha256,
    [Parameter(Mandatory=$true)][string]$RunDirectory
)
$ErrorActionPreference='Stop'
function New-Plan17QueueArguments {
    param([string]$Phase, $Request, [string]$Python, [string]$Runq, [string[]]$Command)
    if($Phase -in @('q23','q24')) {
        $taskBoundTicket=$Request.phases.$Phase.ticket
        if($taskBoundTicket -isnot [string] -or $taskBoundTicket -cnotmatch '\Aq[1-9][0-9]*\z') {
            throw 'Proof phase has no exact request-bound queue ticket'
        }
        return @($Python,'-B','-I',$Runq,'run','--strict-admission',$taskBoundTicket,'--') + $Command
    }
    return @($Python,'-B','-I',$Runq,'small','--cores','1','--gib','1','--') + $Command
}
$taskPython='C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe'
$taskRunq='C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/q/runq.py'
$taskUtilityPython='C:/Users/LOCAL_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$taskNotify='C:/Users/LOCAL_USER/Documents/Codex/atlas-run-events/launch_notify.py'
$taskCodex='C:/Users/LOCAL_USER/AppData/Local/OpenAI/Codex/bin/a96ca4c1eee0cf35/codex.exe'
$taskDispatcher=Join-Path $PSScriptRoot 'run_plan17.py'
$taskManifest=Join-Path $PSScriptRoot 'REQUEST-r7.json'
$taskManifestBytes=[IO.File]::ReadAllBytes($taskManifest)
$taskHasher=[Security.Cryptography.SHA256]::Create()
try {
    $taskManifestDigest=[BitConverter]::ToString($taskHasher.ComputeHash($taskManifestBytes)).Replace('-','').ToLowerInvariant()
} finally {
    $taskHasher.Dispose()
}
if ($taskManifestDigest -cne $ManifestSha256) {
    throw 'Request identity changed'
}
$taskManifestData=[Text.Encoding]::UTF8.GetString($taskManifestBytes) | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $taskCodex -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'e757246b4de87359e660647fa9514955a0971ff6a30affdd8c145d1d5ece7b84') {
    throw 'Qualified Codex CLI identity changed'
}
$taskSaved=@{}
$taskNames=@(Get-ChildItem Env: | Where-Object {$_.Name -like 'PYTHON*'} | ForEach-Object {$_.Name})
foreach($taskName in @($taskNames + 'PYTHONHASHSEED' + 'PYTHONDONTWRITEBYTECODE' | Select-Object -Unique)) {
    $taskSaved[$taskName]=[Environment]::GetEnvironmentVariable($taskName,'Process')
    [Environment]::SetEnvironmentVariable($taskName,$null,'Process')
}
try {
    $env:PYTHONHASHSEED='0'
    $env:PYTHONDONTWRITEBYTECODE='1'
    $taskCommand=@($taskPython,'-B','-s','-P',$taskDispatcher,
                   '--manifest',$taskManifest,'--sha256',$ManifestSha256,'--phase',$Phase)
    $taskQueueArguments=@(New-Plan17QueueArguments -Phase $Phase -Request $taskManifestData `
        -Python $taskPython -Runq $taskRunq -Command $taskCommand)
    & $taskUtilityPython -B $taskNotify start --run-dir $RunDirectory --codex $taskCodex `
        --owner '<PLAN17_OWNER_THREAD>' `
        --coordinator '<PLAN17_COORDINATOR_THREAD>' `
        --cwd 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10' -- @taskQueueArguments
    $taskExit=$LASTEXITCODE
} finally {
    foreach($taskName in $taskSaved.Keys) {
        [Environment]::SetEnvironmentVariable($taskName,$taskSaved[$taskName],'Process')
    }
}
if($taskExit -ne 0) { throw "Tracked start refused (exit $taskExit); preserve evidence; no automatic retry" }
