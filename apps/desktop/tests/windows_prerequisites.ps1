# Runs the real orchestration with registry/process boundaries replaced. No system installs.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../windows/prerequisites.ps1')

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$realTest = ${function:Test-CairnPrerequisite}
$realInvoke = ${function:Invoke-CairnPrerequisiteInstaller}
function Test-CairnPrerequisite([string]$Id) { return $script:ready[$Id] }
function Invoke-CairnPrerequisiteInstaller($Component, [string]$Directory) {
    $script:attempts.Add($Component.Id)
    if ($script:installFailure) { throw $script:installFailure }
    if ($script:becomesReady) { $script:ready[$Component.Id] = $true }
    return $script:installerExit
}
function Reset-Case {
    $script:ready = @{ dotnet = $true; webview = $true; vcredist = $true }
    $script:attempts = [Collections.Generic.List[string]]::new()
    $script:installerExit = 0
    $script:becomesReady = $true
    $script:installFailure = $null
}

Reset-Case
Assert ((Install-CairnPrerequisites $env:TEMP) -eq 0) 'Existing components should succeed'
Assert ($attempts.Count -eq 0) 'Existing components must not be downloaded or installed'

foreach ($missing in @('dotnet', 'webview', 'vcredist')) {
    Reset-Case
    $ready[$missing] = $false
    Assert ((Install-CairnPrerequisites $env:TEMP) -eq 0) "Missing $missing should be installed"
    Assert ($attempts.Count -eq 1 -and $attempts[0] -eq $missing) 'Only the missing component may be installed'
}

Reset-Case
$ready.vcredist = $false
$becomesReady = $false
Assert ((Install-CairnPrerequisites $env:TEMP) -eq 1) 'Exit zero without readiness must not report success'

foreach ($code in @(3010, 1641)) {
    Reset-Case
    $ready.dotnet = $false
    $ready.webview = $false
    $installerExit = $code
    Assert ((Install-CairnPrerequisites $env:TEMP) -eq 3010) 'Reboot must be returned to the outer installer'
    Assert ($attempts.Count -eq 1) 'Do not continue installing after reboot is required'
}

Reset-Case
$ready.dotnet = $false
$installerExit = 1602
Assert ((Install-CairnPrerequisites $env:TEMP) -eq 1602) 'Cancellation must be preserved'

Reset-Case
$ready.webview = $false
$installerExit = 1603
Assert ((Install-CairnPrerequisites $env:TEMP) -eq 1) 'A failed installer must stop installation'

Reset-Case
$ready.webview = $false
$installFailure = 'Download failed: test network unavailable'
Assert ((Install-CairnPrerequisites $env:TEMP) -eq 1) 'A failed download must stop installation'

# Verify trust failure occurs before a downloaded program can run.
${function:Invoke-CairnPrerequisiteInstaller} = $realInvoke
$script:started = $false
function Save-CairnPrerequisiteDownload([string]$Url, [string]$Path) {
    [IO.File]::WriteAllText($Path, 'unsigned executable fixture')
}
function Get-AuthenticodeSignature { param($LiteralPath)
    return [pscustomobject]@{ Status = 'NotSigned'; SignerCertificate = $null }
}
function Start-Process { $script:started = $true; throw 'Untrusted program was executed' }
$temporary = Join-Path $env:TEMP ('cairn-prerequisite-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $rejected = $false
    try { Invoke-CairnPrerequisiteInstaller $CairnPrerequisites[1] $temporary }
    catch { $rejected = $_.Exception.Message -match 'signature' }
    Assert $rejected 'Unsigned download must be rejected with diagnostic context'
    Assert (-not $started) 'Unsigned download must never be launched'
    Assert (@(Get-ChildItem $temporary).Count -eq 0) 'Temporary download must be removed'

    $certificate = [pscustomobject]@{}
    $certificate | Add-Member ScriptMethod GetNameInfo { return $script:publisher }
    function Get-AuthenticodeSignature { param($LiteralPath)
        return [pscustomobject]@{ Status = 'Valid'; SignerCertificate = $certificate }
    }
    $script:publisher = 'Unrelated Publisher'
    $rejected = $false
    try { Invoke-CairnPrerequisiteInstaller $CairnPrerequisites[1] $temporary }
    catch { $rejected = $_.Exception.Message -match 'signature' }
    Assert $rejected 'A valid signature from an unrelated publisher must be rejected'
    Assert (-not $started) 'An unrelated publisher must never be launched'

    $script:publisher = 'Microsoft Corporation'
    function Start-Process {
        param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $Verb)
        $script:launchVerb = $Verb
        $script:launchArguments = $ArgumentList
        $writeBlocked = $false
        try { $writer = [IO.File]::OpenWrite($FilePath); $writer.Dispose() }
        catch [IO.IOException] { $writeBlocked = $true }
        Assert $writeBlocked 'Verified bytes must remain locked against modification during launch'
        return [pscustomobject]@{ ExitCode = 0 }
    }
    Assert ((Invoke-CairnPrerequisiteInstaller $CairnPrerequisites[2] $temporary) -eq 0) 'Trusted installer should run'
    Assert ($launchVerb -eq 'RunAs' -and $launchArguments -eq '/install /quiet /norestart') 'VC runtime requires UAC and must suppress automatic reboot'
    Assert ((Invoke-CairnPrerequisiteInstaller $CairnPrerequisites[1] $temporary) -eq 0) 'Trusted WebView installer should run'
    Assert (-not $launchVerb -and $launchArguments -eq '/silent /install') 'WebView should use the current user'

    function Start-Process { throw [ComponentModel.Win32Exception]::new(1223) }
    Assert ((Invoke-CairnPrerequisiteInstaller $CairnPrerequisites[0] $temporary) -eq 1602) 'Declined UAC must return cancellation'
    Assert (@(Get-ChildItem $temporary).Count -eq 0) 'Cancelled launch must clean its download'
} finally { Remove-Item -LiteralPath $temporary -Recurse -Force }

Write-Output 'PASS: prerequisites, recheck, reboot, cancellation, failure, signature/publisher rejection, locked bytes, and UAC'
