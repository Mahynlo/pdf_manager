; ============================================================
;  Extraer PDFs - InnoSetup installer script
;  Compila con:  ISCC.exe installer\setup.iss
; ============================================================

#define MyAppName        "Extraer PDFs"
; MyAppVersion y MyAppSourceDir pueden sobreescribirse desde la linea de
; comandos con: ISCC.exe /DMyAppVersion=1.2.3 /DMyAppSourceDir=ruta ...
#ifndef MyAppVersion
  #define MyAppVersion   "0.1.28"
#endif
#define MyAppPublisher   "Flet"
#define MyAppExeName     "extraer_pdfs.exe"
; Puente para "Abrir con": el exe de Flet no arranca si recibe argumentos, asi
; que Windows invoca este launcher, que entrega la ruta por env var / socket IPC.
#define MyAppLauncher    "launcher.exe"
#ifndef MyAppSourceDir
  ; Ruta de salida del build de Flet/Flutter (ajustar si difiere)
  #define MyAppSourceDir "..\build\windows\x64\runner\Release"
#endif
#define MyAppProgID      "ExtraerPdfs.PdfFile"

[Setup]
; GUID unico para esta aplicacion - no cambiar despues del primer release
AppId={{A3F2C1D0-8B4E-4F9A-B6C2-1D3E5F7A9B0C}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Icono del instalador (opcional - descomenta si tienes un .ico)
;SetupIconFile=assets\icon.ico
OutputDir=..\dist
OutputBaseFilename=ExtraerPDFs_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Necesario para registrar asociaciones de archivo
ChangesAssociations=yes
; Requiere admin para escribir en HKLM y HKCR
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon";  Description: "Crear acceso directo en el &escritorio";  GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "assocpdf";     Description: "Abrir archivos PDF con {#MyAppName} (agrega a 'Abrir con')"; GroupDescription: "Asociacion de archivos:"

[Files]
; Copia todo el directorio de salida del build (exe + DLLs + data/)
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}";  Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";      Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; ── ProgID para archivos PDF ───────────────────────────────────────────────
Root: HKCR; Subkey: "{#MyAppProgID}";                          ValueType: string; ValueName: "";        ValueData: "Documento PDF (Extraer PDFs)"; Flags: uninsdeletekey
Root: HKCR; Subkey: "{#MyAppProgID}\DefaultIcon";              ValueType: string; ValueName: "";        ValueData: "{app}\{#MyAppExeName},0"
; IMPORTANTE: se invoca el LAUNCHER, no el exe de Flet (el exe se queda en blanco
; si recibe la ruta como argumento).
Root: HKCR; Subkey: "{#MyAppProgID}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppLauncher}"" ""%1"""

; ── "Abrir con" directo sobre el launcher (entrada "Buscar otra aplicacion") ──
Root: HKCR; Subkey: "Applications\{#MyAppLauncher}";                          ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Applications\{#MyAppLauncher}\DefaultIcon";              ValueType: string; ValueName: "";                ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "Applications\{#MyAppLauncher}\shell\open\command";       ValueType: string; ValueName: "";                ValueData: """{app}\{#MyAppLauncher}"" ""%1"""
Root: HKCR; Subkey: "Applications\{#MyAppLauncher}\SupportedTypes";           ValueType: string; ValueName: ".pdf";            ValueData: ""
; Oculta el exe crudo de "Abrir con" para que nadie elija la variante que se
; queda en blanco; el handler valido es el launcher.
Root: HKCR; Subkey: "Applications\{#MyAppExeName}";                           ValueType: string; ValueName: "NoOpenWith";      ValueData: ""

; ── Registro de capacidades de la aplicacion (modo moderno de Windows) ─────
Root: HKLM; Subkey: "Software\{#MyAppName}";                                          Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities";     ValueType: string; ValueName: "ApplicationName";        ValueData: "{#MyAppName}"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities";     ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Visualiza, extrae texto y aplica OCR a archivos PDF"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyAppProgID}"
Root: HKLM; Subkey: "Software\RegisteredApplications";        ValueType: string; ValueName: "{#MyAppName}";           ValueData: "Software\{#MyAppName}\Capabilities"

; ── Agrega la app a "Abrir con" para .pdf (no cambia el programa predeterminado) ──
Root: HKCR; Subkey: ".pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgID}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocpdf

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent
