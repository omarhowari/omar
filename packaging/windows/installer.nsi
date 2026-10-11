; NSIS installer for TDA (built by build_portable.sh)
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "Sections.nsh"

!define APPNAME "TDA"
!define VERSION "1.5.0"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\TDA"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$PROGRAMFILES64\TDA"
InstallDirRegKey HKLM "Software\TDA" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
BrandingText "TDA ${VERSION} - LAN Messenger (MIT)"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\TDA.exe"
!define MUI_LANGDLL_ALLLANGUAGES

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Arabic"
!insertmacro MUI_LANGUAGE "English"

LangString SecDesktop ${LANG_ARABIC} "اختصار على سطح المكتب"
LangString SecDesktop ${LANG_ENGLISH} "Desktop shortcut"
LangString SecStartup ${LANG_ARABIC} "التشغيل مع بدء Windows"
LangString SecStartup ${LANG_ENGLISH} "Start with Windows"

VIProductVersion "1.5.0.0"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductName" "TDA"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileDescription" "TDA LAN Messenger Setup"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "LegalCopyright" "MIT License"

Section "TDA" SecMain
  SectionIn RO
  ; close a running copy so files can be replaced
  nsExec::Exec 'taskkill /f /im TDA.exe'
  Sleep 700
  ; update in place: replace the program files (settings/history live in %APPDATA%\TDA and are kept)
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\Lib"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  ; keep this installer: TDA gives it to colleagues (LAN updates + "Share the app")
  CreateDirectory "$INSTDIR\setup"
  ${If} "$EXEPATH" != "$INSTDIR\setup\TDA-Setup.exe"
    CopyFiles /SILENT "$EXEPATH" "$INSTDIR\setup\TDA-Setup.exe"
  ${EndIf}
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\TDA" "InstallDir" "$INSTDIR"

  CreateDirectory "$SMPROGRAMS\TDA"
  CreateShortcut "$SMPROGRAMS\TDA\TDA.lnk" "$INSTDIR\TDA.exe"
  CreateShortcut "$SMPROGRAMS\TDA\Uninstall TDA.lnk" "$INSTDIR\Uninstall.exe"

  ; allow incoming LAN connections (messages + files)
  nsExec::Exec 'netsh advfirewall firewall delete rule name="TDA"'
  nsExec::Exec 'netsh advfirewall firewall add rule name="TDA" dir=in action=allow program="$INSTDIR\TDA.exe" enable=yes profile=any'

  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "TDA LAN Messenger"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "TDA Open Source Project"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\TDA.exe"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
SectionEnd

Section "$(SecDesktop)" SecDesk
  CreateShortcut "$DESKTOP\TDA.lnk" "$INSTDIR\TDA.exe"
  WriteRegStr HKLM "Software\TDA" "Desktop" "1"
SectionEnd

Section "$(SecStartup)" SecRun
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TDA" '"$INSTDIR\TDA.exe" --minimized'
  WriteRegStr HKLM "Software\TDA" "Startup" "1"
SectionEnd

Function .onInit
  ${If} ${Silent}
    ; silent update (TDA-Setup.exe /S): keep the choices made at the first installation
    ReadRegStr $0 HKLM "Software\TDA" "InstallDir"
    ${If} $0 != ""
      ReadRegStr $1 HKLM "Software\TDA" "Desktop"
      ${If} $1 != "1"
        !insertmacro UnselectSection ${SecDesk}
      ${EndIf}
      ReadRegStr $1 HKLM "Software\TDA" "Startup"
      ${If} $1 != "1"
        !insertmacro UnselectSection ${SecRun}
      ${EndIf}
    ${EndIf}
  ${Else}
    !insertmacro MUI_LANGDLL_DISPLAY
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  ${If} ${Silent}
    ; start the new version again as the normal (not elevated) user
    Exec '"$WINDIR\explorer.exe" "$INSTDIR\TDA.exe"'
  ${EndIf}
FunctionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /f /im TDA.exe'
  nsExec::Exec 'netsh advfirewall firewall delete rule name="TDA"'
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TDA"
  Delete "$DESKTOP\TDA.lnk"
  RMDir /r "$SMPROGRAMS\TDA"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "Software\TDA"
SectionEnd
