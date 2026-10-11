; NSIS installer for TDA (built by build_portable.sh)
Unicode true
!include "MUI2.nsh"

!define APPNAME "TDA"
!define VERSION "1.4.1"
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

VIProductVersion "1.4.1.0"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductName" "TDA"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileDescription" "TDA LAN Messenger Setup"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "LegalCopyright" "MIT License"

Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

Section "TDA" SecMain
  SectionIn RO
  ; close a running copy so files can be replaced
  nsExec::Exec 'taskkill /f /im TDA.exe'
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
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
SectionEnd

Section "$(SecStartup)" SecRun
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "TDA" '"$INSTDIR\TDA.exe" --minimized'
SectionEnd

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
