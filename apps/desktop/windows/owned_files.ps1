param([string]$InstallDirectory, [string]$ManifestPath)

$ErrorActionPreference = 'Stop'

function Get-CairnOwnershipKey([string]$RelativePath) {
    # Packaged program paths are ASCII. Unicode extra/user files remain unowned.
    if ($RelativePath -match '[^\x00-\x7F]') { return $null }
    $normalized = $RelativePath.Replace('\', '/').ToLowerInvariant()
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized))).Replace('-', '').ToLowerInvariant()
    } finally { $hash.Dispose() }
}

function Remove-CairnObsoleteFiles([string]$Directory, [string]$CurrentManifest) {
    if (-not $Directory -or -not $CurrentManifest) { throw 'An install directory and current payload manifest are required.' }
    $root = Get-Item -LiteralPath $Directory -Force
    if (-not $root.PSIsContainer -or ($root.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The install directory must be an ordinary directory.'
    }
    $rootPath = $root.FullName.TrimEnd('\')
    $marker = Join-Path $rootPath '.cairn-install.marker'
    $ownership = Join-Path $rootPath '.cairn-owned.ini'
    foreach ($file in @($marker, $ownership)) {
        $item = Get-Item -LiteralPath $file -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Installer metadata is not an ordinary file: $file"
        }
    }
    if ([IO.File]::ReadAllText($marker) -ne 'Cairn.Desktop.PerUser.Install.v1') { throw 'Invalid Cairn install marker.' }
    if ((Get-Item -LiteralPath $ownership).Length -gt 8MB) { throw 'The ownership manifest is too large.' }
    $owned = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $section = $false
    foreach ($line in [IO.File]::ReadAllLines($ownership)) {
        $value = $line.Trim()
        if (-not $value -or $value.StartsWith(';')) { continue }
        if ($value -eq '[files]') { $section = $true; continue }
        if (-not $section -or $value -notmatch '^([a-fA-F0-9]{64})=1$') {
            throw 'Invalid installer ownership manifest; no files were removed.'
        }
        [void]$owned.Add($Matches[1].ToLowerInvariant())
    }
    if ($owned.Count -eq 0) { throw 'The installer ownership manifest is empty.' }
    foreach ($name in @('.cairn-install.marker', '.cairn-owned.ini', 'Uninstall.exe', 'settings.json', 'model-settings.dpapi', 'workspace-settings.dpapi', 'postgres/PG_VERSION')) {
        if ($owned.Contains((Get-CairnOwnershipKey $name))) { throw 'Ownership metadata claims a reserved/data file.' }
    }
    $manifestFile = Get-Item -LiteralPath $CurrentManifest
    if ($manifestFile.Length -gt 8MB) { throw 'The current payload manifest is too large.' }
    $manifest = [IO.File]::ReadAllText($manifestFile.FullName) | ConvertFrom-Json
    if ($manifest.files -isnot [array] -or $manifest.files.Count -eq 0) { throw 'Invalid current payload manifest.' }
    $current = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($name in $manifest.files) {
        if ($name -isnot [string] -or -not $name) { throw 'Invalid payload file name.' }
        $key = Get-CairnOwnershipKey $name
        if (-not $key) { throw 'Packaged program paths must be ASCII.' }
        [void]$current.Add($key)
    }

    $pending = [Collections.Generic.Stack[IO.DirectoryInfo]]::new()
    $pending.Push($root)
    $remove = [Collections.Generic.List[object]]::new()
    $directories = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    while ($pending.Count -gt 0) {
        $folder = $pending.Pop()
        foreach ($item in $folder.GetFileSystemInfos()) {
            $relative = $item.FullName.Substring($rootPath.Length + 1).Replace('\', '/')
            $key = Get-CairnOwnershipKey $relative
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                if ($key -and $owned.Contains($key)) { throw "An owned file is a link: $relative" }
                continue
            }
            if ($item.Attributes -band [IO.FileAttributes]::Directory) {
                $pending.Push([IO.DirectoryInfo]$item)
                continue
            }
            if (-not $key) { continue }
            if ($owned.Contains($key) -and $item.Name -in @('settings.json', 'model-settings.dpapi', 'workspace-settings.dpapi')) {
                throw "Ownership metadata claims a data file: $relative"
            }
            $obsolete = $owned.Contains($key) -and -not $current.Contains($key)
            $cache = $false
            if ($relative -match '^(.*)/__pycache__/([^/]+)\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc$') {
                $sourceKey = Get-CairnOwnershipKey ($Matches[1] + '/' + $Matches[2] + '.py')
                $cache = $owned.Contains($sourceKey)
            }
            if ($obsolete -or $cache) {
                $remove.Add([pscustomobject]@{ Path=$item.FullName; Cache=$cache })
                $parent = $item.DirectoryName
                while ($parent -and $parent -ne $rootPath) {
                    [void]$directories.Add($parent)
                    $parent = [IO.Path]::GetDirectoryName($parent)
                }
            }
        }
    }

    $cacheCount = 0
    foreach ($item in $remove) {
        # No wildcard deletion and no traversal through directory links.
        $parent = [IO.Path]::GetDirectoryName($item.Path)
        while ($parent -ne $rootPath) {
            if ([IO.File]::GetAttributes($parent) -band [IO.FileAttributes]::ReparsePoint) { throw "A directory became a link: $parent" }
            $parent = [IO.Path]::GetDirectoryName($parent)
        }
        if ([IO.File]::GetAttributes($item.Path) -band [IO.FileAttributes]::ReparsePoint) { throw "A file became a link: $($item.Path)" }
        [IO.File]::Delete($item.Path)
        if ($item.Cache) { $cacheCount++ }
    }
    foreach ($directory in ($directories | Sort-Object Length -Descending)) {
        if ([IO.File]::GetAttributes($directory) -band [IO.FileAttributes]::ReparsePoint) { continue }
        $entries = [IO.Directory]::EnumerateFileSystemEntries($directory).GetEnumerator()
        try { $hasEntries = $entries.MoveNext() } finally { $entries.Dispose() }
        if ($hasEntries) { continue }
        try { [IO.Directory]::Delete($directory, $false) }
        catch [IO.IOException] {
            # A new unknown file may have appeared after the empty-directory check.
            if (($_.Exception.HResult -band 0xffff) -ne 145) { throw }
        }
    }
    return [pscustomobject]@{ ObsoleteFiles=($remove.Count - $cacheCount); PythonCaches=$cacheCount }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $result = Remove-CairnObsoleteFiles -Directory $InstallDirectory -CurrentManifest $ManifestPath
        Write-Output "Removed $($result.ObsoleteFiles) obsolete program files and $($result.PythonCaches) owned Python caches."
        exit 0
    } catch {
        Write-Output "Cairn program cleanup failed: $($_.Exception.Message)"
        exit 1
    }
}
