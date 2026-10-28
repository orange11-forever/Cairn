Unicode true
RequestExecutionLevel user
Name "Cairn ${APP_VERSION}（Windows验证版）"
OutFile "${OUTPUT_FILE}"
Icon "Cairn.ico"
UninstallIcon "Cairn.ico"
InstallDir "$LOCALAPPDATA\Programs\Cairn"
SetCompressor /FINAL zlib
ShowInstDetails show
ShowUninstDetails show
!include MUI2.nsh
!include LogicLib.nsh
!include x64.nsh
!include FileFunc.nsh
!include WordFunc.nsh
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\CairnDesktop"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
!define MARKER "Cairn.Desktop.PerUser.Install.v1"
!define RUNNING_MUTEX "Local\Cairn.Desktop.Running.v1"
!define MAINTENANCE_MUTEX "Local\Cairn.Desktop.Maintenance.v1"
!define WEBVIEW_CLIENT "Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
Var Failure
Var MaintenanceHandle

!macro Fail TEXT
  StrCpy $Failure "${TEXT}"
  Goto failed
!macroend

Function .onInit
  SetShellVarContext current
  SetRegView 64
  Call LockMaintenance
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "Cairn需要64位Windows。" /SD IDOK
    SetErrorLevel 1
    Abort
  ${EndIf}
  ReadRegDWORD $0 HKLM "Software\Microsoft\NET Framework Setup\NDP\v4\Full" "Release"
  IntCmp $0 528040 net_ready net_missing net_ready
net_missing:
  MessageBox MB_ICONSTOP|MB_OK "请先安装.NET Framework 4.8，再运行安装程序。官方地址：https://dotnet.microsoft.com/download/dotnet-framework/net48" /SD IDOK
  SetErrorLevel 1
  Abort
net_ready:
  ReadRegStr $0 HKCU "${WEBVIEW_CLIENT}" "pv"
  Call CheckWebViewVersion
  StrCmp $1 1 prerequisites_ready
  ReadRegStr $0 HKLM "${WEBVIEW_CLIENT}" "pv"
  Call CheckWebViewVersion
  StrCmp $1 1 prerequisites_ready
  SetRegView 32
  ReadRegStr $0 HKCU "${WEBVIEW_CLIENT}" "pv"
  Call CheckWebViewVersion
  StrCmp $1 1 prerequisites_ready
  ReadRegStr $0 HKLM "${WEBVIEW_CLIENT}" "pv"
  Call CheckWebViewVersion
  StrCmp $1 1 prerequisites_ready
  MessageBox MB_ICONSTOP|MB_OK "请先安装Microsoft Edge WebView2 Runtime（不是Edge浏览器），再运行安装程序。官方地址：https://developer.microsoft.com/microsoft-edge/webview2/" /SD IDOK
  SetErrorLevel 1
  Abort
prerequisites_ready:
  SetRegView 64
FunctionEnd

Function CheckWebViewVersion
  StrCpy $1 0
  StrCmp $0 "" version_done
  ${VersionCompare} "$0" "0.0.0.0" $2
  StrCmp $2 1 0 version_done
  StrCpy $1 1
version_done:
FunctionEnd

!macro GuardFunctions PREFIX
Function ${PREFIX}LockMaintenance
  System::Call 'kernel32::CreateMutexW(p 0, i 1, w "${MAINTENANCE_MUTEX}") p .r0 ?e'
  Pop $1
  StrCmp $0 0 maintenance_busy
  StrCpy $MaintenanceHandle $0
  StrCmp $1 183 maintenance_busy
  Return
maintenance_busy:
  MessageBox MB_ICONSTOP|MB_OK "Cairn正在启动，或另一个安装/卸载程序正在运行。请等待该操作结束后重试。" /SD IDOK
  SetErrorLevel 1
  Abort
FunctionEnd

Function ${PREFIX}CheckLink
  Pop $R0
  System::Call 'kernel32::GetFileAttributesW(w r10) i .r11 ?e'
  Pop $R2
  IntCmp $R1 -1 missing_path
  IntOp $R1 $R1 & 0x400
  IntCmp $R1 0 link_done
  Goto unsafe_link
missing_path:
  StrCmp $R2 2 link_done
  StrCmp $R2 3 link_done
unsafe_link:
  MessageBox MB_ICONSTOP|MB_OK "目录或文件是链接/联接，或无法安全读取：$R0。操作已停止，尚未修改程序文件。请使用独立的普通本地目录。" /SD IDOK
  SetErrorLevel 1
  Abort
link_done:
FunctionEnd

Function ${PREFIX}CheckDirectory
  System::Call 'kernel32::GetFullPathNameW(w "$INSTDIR", i ${NSIS_MAX_STRLEN}, w .r0, p 0) i .r1'
  IntCmp $1 0 unsafe unsafe
  IntCmp $1 ${NSIS_MAX_STRLEN} unsafe 0 unsafe
  StrCpy $INSTDIR $0
  ; PostgreSQL initdb embeds its program path in SQL using the Windows code page.
  ; Reject unsupported paths before any extraction instead of failing on first run.
  StrLen $0 $INSTDIR
  IntOp $0 $0 + 1
  System::Call 'kernel32::WideCharToMultiByte(i 65001, i 0, w "$INSTDIR", i -1, p 0, i 0, p 0, p 0) i .r1'
  IntCmp $1 $0 ascii_path
  MessageBox MB_ICONSTOP|MB_OK "当前随包PostgreSQL要求程序安装路径仅含ASCII字符（英文、数字及符号，可含空格）。请选择不含中文等非ASCII字符的程序目录；项目数据目录仍可使用中文。尚未修改程序文件。" /SD IDOK
  SetErrorLevel 1
  Abort
ascii_path:
  StrCpy $8 $INSTDIR
check_ancestors:
  Push $8
  Call ${PREFIX}CheckLink
  ${GetParent} "$8" $8
  StrCmp $8 "" ancestors_done
  Goto check_ancestors
ancestors_done:
  ${GetRoot} "$INSTDIR" $0
  StrCmp $INSTDIR $0 unsafe
  StrCmp $INSTDIR "$0\" unsafe
  StrCmp $INSTDIR "$PROFILE" unsafe
  StrCmp $INSTDIR "$DESKTOP" unsafe
  StrCmp $INSTDIR "$LOCALAPPDATA" unsafe
  StrCmp $INSTDIR "$APPDATA" unsafe
  StrCmp $INSTDIR "$PROGRAMFILES" unsafe
  StrCmp $INSTDIR "$PROGRAMFILES64" unsafe
  StrCmp $INSTDIR "$WINDIR" unsafe
  StrCmp $INSTDIR "$SYSDIR" unsafe
  StrCpy $0 "$LOCALAPPDATA\Cairn\"
  StrLen $1 $0
  StrCpy $2 "$INSTDIR\" $1
  StrCmp $2 $0 unsafe
  IfFileExists "$INSTDIR\settings.json" unsafe
  IfFileExists "$INSTDIR\postgres\PG_VERSION" unsafe
  Push "$INSTDIR\.cairn-install.marker"
  Call ${PREFIX}CheckLink
  Push "$INSTDIR\.cairn-owned.ini"
  Call ${PREFIX}CheckLink
  Push "$INSTDIR\Uninstall.exe"
  Call ${PREFIX}CheckLink
  Return
unsafe:
  MessageBox MB_ICONSTOP|MB_OK "请选择独立程序目录，不能选择磁盘根目录、用户/桌面目录或Cairn数据目录。数据目录不会被安装或卸载修改。" /SD IDOK
  SetErrorLevel 1
  Abort
FunctionEnd

Function ${PREFIX}CheckStopped
  System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "${RUNNING_MUTEX}") p .r0 ?e'
  Pop $1
  StrCmp $0 0 no_mutex
  System::Call 'kernel32::CloseHandle(p r0)'
  Goto running
no_mutex:
  IntCmp $1 2 check_native running running
check_native:
  Push "$INSTDIR\Cairn.exe"
  Call ${PREFIX}CheckWritable
  Push "$INSTDIR\python\python.exe"
  Call ${PREFIX}CheckWritable
  Push "$INSTDIR\postgres\bin\postgres.exe"
  Call ${PREFIX}CheckWritable
  Return
running:
  MessageBox MB_ICONSTOP|MB_OK "Cairn或其本地服务仍在运行，或无法确认其已停止。请正常关闭Cairn及此目录的服务后重试；安装程序不会结束其他Python/PostgreSQL进程。" /SD IDOK
  SetErrorLevel 1
  Abort
FunctionEnd

Function ${PREFIX}CheckWritable
  Pop $3
  IfFileExists "$3" 0 writable_done
  System::Call 'kernel32::CreateFileW(w r3, i 0x40000000, i 7, p 0, i 3, i 0, p 0) p .r0'
  StrCmp $0 -1 not_writable
  System::Call 'kernel32::CloseHandle(p r0)'
  Return
not_writable:
  MessageBox MB_ICONSTOP|MB_OK "程序文件仍被占用或不可写：$3。请正常关闭此目录的Cairn/服务并检查目录权限后重试。尚未修改安装文件。" /SD IDOK
  SetErrorLevel 1
  Abort
writable_done:
FunctionEnd

Function ${PREFIX}CheckMarker
  ClearErrors
  FileOpen $0 "$INSTDIR\.cairn-install.marker" r
  IfErrors marker_invalid
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "${MARKER}" marker_valid
marker_invalid:
  MessageBox MB_ICONSTOP|MB_OK "此目录没有有效的Cairn安装标记，操作已拒绝。请选择空目录安装，或使用此安装包创建的程序目录。" /SD IDOK
  SetErrorLevel 1
  Abort
marker_valid:
FunctionEnd
!macroend
!insertmacro GuardFunctions ""
!insertmacro GuardFunctions "un."

Section "Cairn"
  SetShellVarContext current
  SetRegView 64
  Call CheckDirectory
  Call CheckStopped
  ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  StrCmp $0 "" check_target
  StrCmp $0 $INSTDIR check_target
  !insertmacro Fail "当前用户已有另一个安装目录：$0。请选原目录升级，或先卸载旧程序（数据会保留）。"
check_target:
  IfFileExists "$INSTDIR\.cairn-install.marker" marked_target
  FindFirst $0 $1 "$INSTDIR\*"
empty_check:
  StrCmp $1 "" empty_target
  StrCmp $1 "." empty_next
  StrCmp $1 ".." empty_next
  FindClose $0
  !insertmacro Fail "所选目录不是空目录且没有Cairn安装标记，尚未修改任何文件。请另选空目录。"
empty_next:
  FindNext $0 $1
  Goto empty_check
empty_target:
  FindClose $0
  IfFileExists "$SMPROGRAMS\Cairn.lnk" 0 install_ready
  !insertmacro Fail "已存在同名开始菜单快捷方式，无法确认归属。请保留它并另行处理后重试。"
marked_target:
  Call CheckMarker
install_ready:
  !include "payload-check.nsh"
  ClearErrors
  CreateDirectory "$INSTDIR"
  IfErrors install_failed
  FileOpen $0 "$INSTDIR\.cairn-install.marker" w
  IfErrors install_failed
  FileWrite $0 "${MARKER}"
  FileClose $0
  IfErrors install_failed
  SetOverwrite try
  !include "payload-install.nsh"
  ClearErrors
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  IfErrors install_failed
  CreateShortCut "$SMPROGRAMS\Cairn.lnk" "$INSTDIR\Cairn.exe"
  IfErrors install_failed
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "Cairn（Windows验证版）"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "Cairn"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" '$\"$INSTDIR\Cairn.exe$\",0'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  IfErrors install_failed
  SetErrorLevel 0
  Goto completed
install_failed:
  StrCpy $Failure "安装文件写入失败，安装未完成。请检查目录权限/占用情况并重新运行；已有数据目录未被删除。"
failed:
  MessageBox MB_ICONSTOP|MB_OK "$Failure" /SD IDOK
  SetErrorLevel 1
  Abort
completed:
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  Call un.LockMaintenance
  Call un.CheckDirectory
  Call un.CheckMarker
  Call un.CheckStopped
  !include "payload-uninstall-check.nsh"
FunctionEnd

Section "Uninstall"
  !include "payload-uninstall.nsh"
  ClearErrors
  Delete "$INSTDIR\.cairn-owned.ini"
  IfErrors uninstall_failed
  Delete "$INSTDIR\Uninstall.exe"
  IfErrors uninstall_failed
  ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  StrCmp $0 $INSTDIR 0 preserve_other_registration
  ClearErrors
  Delete "$SMPROGRAMS\Cairn.lnk"
  IfErrors uninstall_failed
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  IfErrors uninstall_failed
preserve_other_registration:
  ClearErrors
  Delete "$INSTDIR\.cairn-install.marker"
  IfErrors uninstall_failed
  RMDir "$INSTDIR"
  SetErrorLevel 0
  Goto uninstall_completed
uninstall_failed:
  MessageBox MB_ICONSTOP|MB_OK "卸载文件删除失败，卸载未完成。请关闭此目录中的程序/服务后重试。项目数据保持不变。" /SD IDOK
  SetErrorLevel 1
  Abort
uninstall_completed:
SectionEnd
