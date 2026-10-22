param(
    [Parameter(Mandatory=$true)][string]$Manifest,
    [Parameter(Mandatory=$true)][string]$ManifestSha256
)
$ErrorActionPreference='Stop'
# One source-only control. Only the pinned argument function is extracted; the
# launcher's top-level statements, helper, queue, environment and science stay idle.
$taskManifestPath=[IO.Path]::GetFullPath($Manifest)
$taskManifestBytes=[IO.File]::ReadAllBytes($taskManifestPath)
$taskHasher=[Security.Cryptography.SHA256]::Create()
try {
    $taskDigest=[BitConverter]::ToString($taskHasher.ComputeHash($taskManifestBytes)).Replace('-','').ToLowerInvariant()
} finally {
    $taskHasher.Dispose()
}
if($taskDigest -cne $ManifestSha256) { throw 'Control fixture identity changed' }
$taskRequest=[Text.Encoding]::UTF8.GetString($taskManifestBytes) | ConvertFrom-Json
$taskLauncher=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'launch.ps1'))
$taskLauncherBytes=[IO.File]::ReadAllBytes($taskLauncher)
$taskHasher=[Security.Cryptography.SHA256]::Create()
try {
    $taskLauncherDigest=[BitConverter]::ToString($taskHasher.ComputeHash($taskLauncherBytes)).Replace('-','').ToLowerInvariant()
} finally {
    $taskHasher.Dispose()
}
$taskLauncherPin=$taskRequest.pins.PSObject.Properties[$taskLauncher]
if($null -eq $taskLauncherPin -or $taskLauncherPin.Value -isnot [string] -or
   $taskLauncherPin.Value -cne $taskLauncherDigest) { throw 'Launcher is not fixture-pinned' }
$taskTokens=$null
$taskParseErrors=$null
$taskAst=[System.Management.Automation.Language.Parser]::ParseInput(
    [Text.Encoding]::UTF8.GetString($taskLauncherBytes),[ref]$taskTokens,[ref]$taskParseErrors)
if(@($taskParseErrors).Count -ne 0) { throw 'Pinned launcher has parse errors' }
$taskFunctions=@($taskAst.FindAll({param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -ceq 'New-Plan17QueueArguments'
},$true))
if($taskFunctions.Count -ne 1) { throw 'Need exactly one pinned queue argument function' }
. ([scriptblock]::Create($taskFunctions[0].Extent.Text))

$taskAssertArguments={param([object[]]$Actual,[string[]]$Expected,[string]$Label)
    if($Actual.Count -ne $Expected.Count) { throw "$Label argument count differs" }
    for($taskIndex=0; $taskIndex -lt $Expected.Count; $taskIndex++) {
        if($Actual[$taskIndex] -isnot [string] -or $Actual[$taskIndex] -cne $Expected[$taskIndex]) {
            throw "$Label argument $taskIndex differs"
        }
    }
}
$taskPython=[string]$taskRequest.interpreter_binding.venv_executable
$taskRunq=Join-Path ([IO.Path]::GetDirectoryName([string]$taskRequest.queue)) 'runq.py'
$taskDispatcher=Join-Path $PSScriptRoot 'run_plan17.py'
$taskCommand=@($taskPython,'-B','-s','-P',$taskDispatcher,
    '--manifest',$taskManifestPath,'--sha256',$ManifestSha256,'--phase','q23')
if($taskRequest.phases.q23.ticket -cne 'q63') { throw 'Fixture must bind scientific q23 to q63' }
$taskActual=@(New-Plan17QueueArguments -Phase 'q23' -Request $taskRequest `
    -Python $taskPython -Runq $taskRunq -Command $taskCommand)
& $taskAssertArguments $taskActual (@($taskPython,'-B','-I',$taskRunq,'run','--strict-admission','q63','--') + $taskCommand) 'q23/q63'

# q24 is an independent in-memory metadata mapping, never a queue allocation.
$taskQ24Request=[pscustomobject]@{phases=[pscustomobject]@{
    q23=[pscustomobject]@{ticket='q63'}; q24=[pscustomobject]@{ticket='q24'}
}}
$taskQ24Command=@($taskCommand)
$taskQ24Command[$taskQ24Command.Count-1]='q24'
$taskActual=@(New-Plan17QueueArguments -Phase 'q24' -Request $taskQ24Request `
    -Python $taskPython -Runq $taskRunq -Command $taskQ24Command)
& $taskAssertArguments $taskActual (@($taskPython,'-B','-I',$taskRunq,'run','--strict-admission','q24','--') + $taskQ24Command) 'q24 mapping'
foreach($taskSmallPhase in @('controls','repeats23','repeats24')) {
    $taskSmallCommand=@($taskCommand)
    $taskSmallCommand[$taskSmallCommand.Count-1]=$taskSmallPhase
    $taskActual=@(New-Plan17QueueArguments -Phase $taskSmallPhase -Request $taskRequest `
        -Python $taskPython -Runq $taskRunq -Command $taskSmallCommand)
    & $taskAssertArguments $taskActual (@($taskPython,'-B','-I',$taskRunq,'small','--cores','1','--gib','1','--') + $taskSmallCommand) $taskSmallPhase
}
$taskBadRequests=@([pscustomobject]@{phases=[pscustomobject]@{q23=[pscustomobject]@{}}})
foreach($taskBadTicket in @($null,63,$true,'','q0','q01','Q63','q63 ',"q63`n")) {
    $taskBadRequests+= [pscustomobject]@{phases=[pscustomobject]@{q23=[pscustomobject]@{ticket=$taskBadTicket}}}
}
foreach($taskBadRequest in $taskBadRequests) {
    $taskRefused=$false
    try {
        $null=@(New-Plan17QueueArguments -Phase 'q23' -Request $taskBadRequest `
            -Python $taskPython -Runq $taskRunq -Command $taskCommand)
    } catch {
        if($_.Exception.Message -cne 'Proof phase has no exact request-bound queue ticket') { throw }
        $taskRefused=$true
    }
    if(-not $taskRefused) { throw 'Missing or malformed queue ticket was accepted' }
}
Write-Output 'PASS: one source-only launcher ticket control'
