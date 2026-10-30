# Used by NSIS before extracting Cairn. Windows PowerShell is part of supported Windows 11.
# Official download links; every downloaded executable must have a valid Microsoft signature.
$CairnPrerequisites = @(
    @{ Id = 'dotnet'; Name = '.NET Framework 4.8'; Url = 'https://go.microsoft.com/fwlink/?LinkId=2085155'; Arguments = '/q /norestart'; Elevate = $true },
    @{ Id = 'webview'; Name = 'Microsoft Edge WebView2 Runtime'; Url = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'; Arguments = '/silent /install'; Elevate = $false },
    @{ Id = 'vcredist'; Name = 'Visual C++ v14 Runtime (x64)'; Url = 'https://aka.ms/vc14/vc_redist.x64.exe'; Arguments = '/install /quiet /norestart'; Elevate = $true }
)

function Get-CairnRegistryValue($Hive, $View, [string]$Path, [string]$Name) {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($Hive, $View)
    $key = $null
    try {
        $key = $base.OpenSubKey($Path)
        if ($null -ne $key) { return $key.GetValue($Name) }
    } finally {
        if ($null -ne $key) { $key.Dispose() }
        $base.Dispose()
    }
}

function Test-CairnPrerequisite([string]$Id) {
    switch ($Id) {
        'dotnet' {
            $release = Get-CairnRegistryValue LocalMachine Registry64 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' 'Release'
            return $null -ne $release -and $release -ge 528040
        }
        'webview' {
            foreach ($hive in @('CurrentUser', 'LocalMachine')) {
                foreach ($view in @('Registry32', 'Registry64')) {
                    $value = Get-CairnRegistryValue $hive $view 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' 'pv'
                    $version = $null
                    if ([version]::TryParse([string]$value, [ref]$version) -and $version -gt [version]'0.0.0.0') { return $true }
                }
            }
            return $false
        }
        'vcredist' {
            # pgvector was built with MSVC 14.44.35207. Check x64 DLLs, not an x86 registration.
            foreach ($name in @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')) {
                $path = Join-Path ([Environment]::GetFolderPath('System')) $name
                if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
                $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
                $version = [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart)
                if ($version -lt [version]'14.44.35207.0') { return $false }
            }
            return $true
        }
        default { throw "Unknown prerequisite: $Id" }
    }
}

function Save-CairnPrerequisiteDownload([string]$Url, [string]$Path) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $request = [Net.HttpWebRequest]::Create($Url)
    $request.Timeout = 300000
    $request.ReadWriteTimeout = 300000
    $response = $inputStream = $outputStream = $null
    try {
        $response = $request.GetResponse()
        if ($response.ResponseUri.Scheme -ne 'https') { throw 'Download redirected to a non-HTTPS URL.' }
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $buffer = New-Object byte[] 65536
        $received = 0L
        $nextReport = 0L
        while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $outputStream.Write($buffer, 0, $read)
            $received += $read
            if ($received -ge $nextReport) {
                if ($response.ContentLength -gt 0) {
                    Write-Host ('Download: {0}% ({1:N1} / {2:N1} MB)' -f [math]::Floor(100 * $received / $response.ContentLength), ($received / 1MB), ($response.ContentLength / 1MB))
                } else { Write-Host ('Downloaded: {0:N1} MB' -f ($received / 1MB)) }
                $nextReport = $received + 1MB
            }
        }
        if ($response.ContentLength -ge 0 -and $received -ne $response.ContentLength) { throw 'Download ended before all bytes were received.' }
        Write-Host ('Download complete: {0:N1} MB' -f ($received / 1MB))
    } finally {
        if ($null -ne $outputStream) { $outputStream.Dispose() }
        if ($null -ne $inputStream) { $inputStream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
    }
}

function Invoke-CairnPrerequisiteInstaller($Component, [string]$Directory) {
    $path = Join-Path $Directory ($Component.Id + '.exe')
    $locked = $null
    try {
        Write-Host ('Downloading {0} from Microsoft...' -f $Component.Name)
        Save-CairnPrerequisiteDownload $Component.Url $path
        # Keep the verified bytes immutable until the installer exits.
        $locked = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $signature = Get-AuthenticodeSignature -LiteralPath $path
        if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
            $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -ne 'Microsoft Corporation') {
            throw "Microsoft signature verification failed for $($Component.Name). Download was not executed."
        }
        Write-Host ('Installing {0}. Approve the Windows authorization prompt if shown...' -f $Component.Name)
        $options = @{ FilePath = $path; ArgumentList = $Component.Arguments; Wait = $true; PassThru = $true }
        if ($Component.Elevate) { $options.Verb = 'RunAs' }
        try {
            $process = Start-Process @options
            return $process.ExitCode
        } catch {
            $cause = $_.Exception
            while ($null -ne $cause) {
                if ($cause -is [ComponentModel.Win32Exception] -and $cause.NativeErrorCode -eq 1223) { return 1602 }
                $cause = $cause.InnerException
            }
            throw
        }
    } finally {
        if ($null -ne $locked) { $locked.Dispose() }
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
}

function Install-CairnPrerequisites([string]$Directory) {
    $ErrorActionPreference = 'Stop'
    try {
        foreach ($component in $CairnPrerequisites) {
            if (Test-CairnPrerequisite $component.Id) {
                Write-Host ($component.Name + ': ready')
                continue
            }
            $code = Invoke-CairnPrerequisiteInstaller $component $Directory
            if ($code -eq 3010 -or $code -eq 1641) {
                Write-Host ($component.Name + ': restart Windows, then run Cairn Setup again. No automatic restart will be requested by Cairn.')
                return 3010
            }
            if ($code -eq 1602) {
                Write-Host ($component.Name + ': installation or Windows authorization was cancelled.')
                return 1602
            }
            if ($code -ne 0) { throw "$($component.Name) installer failed (exit $code)." }
            if (-not (Test-CairnPrerequisite $component.Id)) { throw "$($component.Name) is still unavailable after installation." }
        }
        Write-Host 'All Cairn prerequisites are ready.'
        return 0
    } catch {
        Write-Host ('Prerequisite preparation failed [{0}]: {1}' -f $component.Name, $_.Exception.Message)
        return 1
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference = 'Stop'
    exit (Install-CairnPrerequisites $PSScriptRoot)
}
