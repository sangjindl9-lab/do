; Google Auto Tester Agent - Windows 설치 마법사 (Inno Setup 6)
#define AppName "Google Auto Tester Agent"
#define AppVersion "1.0.0"

[Setup]
AppId={{6B6F1E0E-3C0B-4E5E-9C59-0A5E7C1D2A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Google Auto Tester (독립 제3자 서비스, Google 비공식)
DefaultDirName={autopf}\GoogleAutoTesterAgent
DefaultGroupName={#AppName}
OutputDir=..\..\dist
OutputBaseFilename=GoogleAutoTesterAgent-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName={#AppName}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Windows 시작 시 관리 창(트레이) 자동 실행"; GroupDescription: "실행 방식:"
Name: "service"; Description: "Windows 서비스로 등록 (로그인하지 않아도 백그라운드 실행, 장애 시 자동 재시작)"; GroupDescription: "실행 방식:"; Flags: unchecked
Name: "desktopicon"; Description: "바탕 화면 바로 가기"; GroupDescription: "바로 가기:"; Flags: unchecked

[Files]
Source: "..\..\dist\app\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\GoogleAutoTesterAgent.exe"
Name: "{group}\제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\GoogleAutoTesterAgent.exe"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GoogleAutoTesterAgent"; ValueData: """{app}\GoogleAutoTesterAgent.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\GoogleAutoTesterAgentService.exe"; Parameters: "--startup auto install"; Flags: runhidden; Tasks: service
Filename: "{sys}\sc.exe"; Parameters: "failure GoogleAutoTesterAgent reset= 86400 actions= restart/5000/restart/30000/restart/60000"; Flags: runhidden; Tasks: service
Filename: "{app}\GoogleAutoTesterAgent.exe"; Description: "관리 창 열기 (서버 주소와 등록 코드 입력)"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\GoogleAutoTesterAgentService.exe"; Parameters: "stop"; Flags: runhidden; RunOnceId: "StopSvc"
Filename: "{app}\GoogleAutoTesterAgentService.exe"; Parameters: "remove"; Flags: runhidden; RunOnceId: "RemoveSvc"
