; Inno Setup script — builds WaraqPDF-Setup.exe from dist\WaraqPDF (run build.bat first)
#define AppName "Waraq PDF"
#define AppVersion "1.0.0"
[Setup]
AppId={{6C3E2B8A-5D2E-4A63-9B54-7E0F0B1A9C21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ammar
DefaultDirName={autopf}\WaraqPDF
DefaultGroupName={#AppName}
OutputBaseFilename=WaraqPDF-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Open PDF files with Waraq PDF"; GroupDescription: "File associations:"; Flags: unchecked
[Files]
Source: "dist\WaraqPDF\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\Waraq PDF"; Filename: "{app}\WaraqPDF.exe"
Name: "{group}\Waraq PDF Tools"; Filename: "{app}\WaraqPDF.exe"; Parameters: "--tools"
Name: "{autodesktop}\Waraq PDF"; Filename: "{app}\WaraqPDF.exe"; Tasks: desktopicon
[Registry]
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "WaraqPDF.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\WaraqPDF.Document"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\WaraqPDF.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\WaraqPDF.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\WaraqPDF.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\WaraqPDF.exe"" ""%1"""; Tasks: assoc
[Run]
Filename: "{app}\WaraqPDF.exe"; Description: "{cm:LaunchProgram,Waraq PDF}"; Flags: nowait postinstall skipifsilent
