$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../windows/owned_files.ps1')

function Assert($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Write-FixtureFile([string]$Root, [string]$Name, [string]$Value) {
    $path = Join-Path $Root $Name
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
    [IO.File]::WriteAllText($path, $Value)
}
function New-Fixture([string]$Name) {
    $root = Join-Path $temporary $Name
    [void][IO.Directory]::CreateDirectory($root)
    Write-FixtureFile $root '.cairn-install.marker' 'Cairn.Desktop.PerUser.Install.v1'
    # SHA-256 values from the installer's lowercase ASCII relative-path contract.
    Write-FixtureFile $root '.cairn-owned.ini' @'
[files]
da7e0b9ad6bf761121beb54c666509ed042004ca924ef86f130e90794033d306=1
7881ff5ec4a5b04e16950380333da313d181a36c76e9d02dc184467f697eebc6=1
65124a9bcb6dc20558509e209368475870b319ebbe7c24a26913619e05e78384=1
'@
    Write-FixtureFile $root 'app/current.py' 'current owned source'
    Write-FixtureFile $root 'web/assets/old.js' 'retired owned asset'
    Write-FixtureFile $root 'app/__pycache__/current.cpython-313.pyc' 'owned cache'
    Write-FixtureFile $root 'app/__pycache__/current.cpython-313.opt-1.pyc' 'owned optimized cache'
    Write-FixtureFile $root 'app/__pycache__/removed.cpython-313.pyc' 'cache for an absent formerly owned source'
    Write-FixtureFile $root 'app/user.py' 'user extension'
    Write-FixtureFile $root 'app/__pycache__/user.cpython-313.pyc' 'user extension cache'
    Write-FixtureFile $root 'app/笔记.txt' 'user Unicode notes'
    Write-FixtureFile $root 'my-data/model-settings.dpapi' 'user encrypted data'
    Write-FixtureFile $root 'web/assets/user.js' 'unknown extra asset'
    [void][IO.Directory]::CreateDirectory((Join-Path $root 'user-empty-directory'))
    $manifest = Join-Path $temporary ($Name + '.json')
    [IO.File]::WriteAllText($manifest, '{"files":["app/current.py"]}')
    return @{ Root=$root; Manifest=$manifest }
}
function Assert-UserFiles($Fixture) {
    foreach ($name in @('app/user.py', 'app/__pycache__/user.cpython-313.pyc', 'app/笔记.txt', 'my-data/model-settings.dpapi', 'web/assets/user.js')) {
        Assert (Test-Path -LiteralPath (Join-Path $Fixture.Root $name)) "Unknown/user file removed: $name"
    }
    Assert (Test-Path -LiteralPath (Join-Path $Fixture.Root 'user-empty-directory')) 'Unknown empty directory removed'
    Assert ([IO.File]::ReadAllText((Join-Path $Fixture.Root 'my-data/model-settings.dpapi')) -eq 'user encrypted data') 'User data changed'
}

$temporary = Join-Path $env:TEMP ('cairn-owned-files-' + [guid]::NewGuid())
[void][IO.Directory]::CreateDirectory($temporary)
$junction = $null
try {
    $fixture = New-Fixture 'normal'
    $result = Remove-CairnObsoleteFiles $fixture.Root $fixture.Manifest
    Assert ($result.ObsoleteFiles -eq 1 -and $result.PythonCaches -eq 3) 'Owned obsolete files and derived caches were not fully removed'
    Assert (Test-Path -LiteralPath (Join-Path $fixture.Root 'app/current.py')) 'Current static payload must remain for NSIS deletion'
    Assert (-not (Test-Path -LiteralPath (Join-Path $fixture.Root 'web/assets/old.js'))) 'Legacy owned asset remains'
    Assert-UserFiles $fixture

    $fixture = New-Fixture 'invalid'
    Add-Content -LiteralPath (Join-Path $fixture.Root '.cairn-owned.ini') -Value '../escape=1'
    $rejected = $false
    try { Remove-CairnObsoleteFiles $fixture.Root $fixture.Manifest | Out-Null } catch { $rejected = $true }
    Assert $rejected 'Malformed ownership metadata was accepted'
    Assert (Test-Path -LiteralPath (Join-Path $fixture.Root 'web/assets/old.js')) 'Malformed metadata caused partial deletion'
    Assert (Test-Path -LiteralPath (Join-Path $fixture.Root 'app/__pycache__/current.cpython-313.pyc')) 'Malformed metadata removed a cache'
    Assert-UserFiles $fixture

    $fixture = New-Fixture 'reserved'
    Add-Content -LiteralPath (Join-Path $fixture.Root '.cairn-owned.ini') -Value 'e9e1aabe0aae56cb1eba125e053b355aaf43680cf243ee7b518e1c897e5868c1=1'
    $rejected = $false
    try { Remove-CairnObsoleteFiles $fixture.Root $fixture.Manifest | Out-Null } catch { $rejected = $true }
    Assert $rejected 'Ownership metadata claiming data was accepted'
    Assert (Test-Path -LiteralPath (Join-Path $fixture.Root 'web/assets/old.js')) 'Reserved-file rejection was not atomic'

    $fixture = New-Fixture 'locked'
    $held = [IO.File]::Open((Join-Path $fixture.Root 'web/assets/old.js'), [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $rejected = $false
        try { Remove-CairnObsoleteFiles $fixture.Root $fixture.Manifest | Out-Null } catch { $rejected = $true }
        Assert $rejected 'Locked owned file was reported as removed'
        Assert (Test-Path -LiteralPath (Join-Path $fixture.Root '.cairn-owned.ini')) 'Failure removed ownership metadata'
        Assert (Test-Path -LiteralPath (Join-Path $fixture.Root 'app/current.py')) 'Failure removed the current payload'
        Assert-UserFiles $fixture
    } finally { $held.Dispose() }
    Remove-CairnObsoleteFiles $fixture.Root $fixture.Manifest | Out-Null
    Assert (-not (Test-Path -LiteralPath (Join-Path $fixture.Root 'web/assets/old.js'))) 'Retry after releasing a file lock did not recover'

    $fixture = New-Fixture 'junction'
    $outside = Join-Path $temporary 'outside'
    Write-FixtureFile $outside 'keep.txt' 'outside user content'
    $junction = Join-Path $fixture.Root 'extra-link'
    New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null
    Remove-CairnObsoleteFiles $fixture.Root $fixture.Manifest | Out-Null
    Assert (Test-Path -LiteralPath $junction) 'Unknown junction was removed'
    Assert ([IO.File]::ReadAllText((Join-Path $outside 'keep.txt')) -eq 'outside user content') 'Cleanup followed a junction'
    Assert-UserFiles $fixture
    Write-Output 'PASS: obsolete ownership, derived bytecode, unknown data, corrupt/reserved metadata, locked-file recovery and junction isolation'
} finally {
    if ($junction -and (Test-Path -LiteralPath $junction)) { [IO.Directory]::Delete($junction) }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
