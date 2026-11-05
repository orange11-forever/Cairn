Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CairnTerminalNative {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetConsoleCtrlHandler(IntPtr handler, bool add);
}
'@
if (-not [CairnTerminalNative]::SetConsoleCtrlHandler([IntPtr]::Zero, $false)) {
    throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
}
Set-PSReadLineOption -HistorySaveStyle SaveNothing -ErrorAction Stop
[Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding

function global:prompt {
    $commandSucceeded = $?
    $commandExit = $global:LASTEXITCODE
    $escape = [char]27
    $displayPath = $executionContext.SessionState.Path.CurrentLocation.Path
    if ($displayPath.StartsWith($HOME, [StringComparison]::OrdinalIgnoreCase)) {
        $displayPath = '~' + $displayPath.Substring($HOME.Length)
    }
    $branch = & git symbolic-ref --quiet --short HEAD 2>$null
    $global:LASTEXITCODE = $commandExit
    $result = "`n${escape}[48;2;30;51;52m${escape}[1;36m ${displayPath} ${escape}[0m"
    if ($branch) { $result += " ${escape}[48;2;47;40;67m${escape}[1;35m git ${branch} ${escape}[0m" }
    if ($commandSucceeded) {
        $result += "`n${escape}[1;32m$([char]0x276F)${escape}[0m "
    } else {
        $result += " ${escape}[48;2;65;36;46m${escape}[1;31m failed ${escape}[0m`n${escape}[1;31m$([char]0x276F)${escape}[0m "
    }
    $result
}
