; Inno Setup script for Waraq PDF Lite (C# / Windows Forms)
#define AppName "Waraq PDF Lite"
#define AppVersion "1.0.0"
[Setup]
AppId={{9A4F2C71-3B6E-4C8D-9E21-5F7A0B3C4D11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ammar
DefaultDirName={autopf}\WaraqPdfLite
DefaultGroupName={#AppName}
OutputBaseFilename=WaraqPdfLite-Setup-{#AppVersion}
SetupIconFile=WaraqPdfLite\app.ico
UninstallDisplayIcon={app}\WaraqPdfLite.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Open PDF files with Waraq PDF Lite"; GroupDescription: "File associations:"; Flags: unchecked
[Files]
Source: "WaraqPdfLite\bin\Release\net48\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: "*.pdb,*.xml"
[Icons]
Name: "{group}\Waraq PDF Lite"; Filename: "{app}\WaraqPdfLite.exe"
Name: "{group}\Uninstall Waraq PDF Lite"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Waraq PDF Lite"; Filename: "{app}\WaraqPdfLite.exe"; Tasks: desktopicon
[Registry]
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "WaraqPdfLite.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\WaraqPdfLite.Document"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\WaraqPdfLite.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\WaraqPdfLite.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\WaraqPdfLite.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\WaraqPdfLite.exe"" ""%1"""; Tasks: assoc
[Run]
Filename: "{app}\WaraqPdfLite.exe"; Description: "{cm:LaunchProgram,Waraq PDF Lite}"; Flags: nowait postinstall skipifsilent
