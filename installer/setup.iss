; ============================================================
;  Extraer PDFs - InnoSetup installer script
;  Compila con:  ISCC.exe installer\setup.iss
;
;  CAMBIOS CLAVE vs versión anterior:
;  - Comando "open" usa SetEnvironmentVariable para pasar la
;    ruta como EXTRAR_PDF_PATH (mecanismo principal con flet build)
;  - El comando también pasa %1 como argv por compatibilidad
;  - Comillas correctas para rutas con espacios
;  - Tarea assocpdf es opt-in (unchecked por defecto)
; ============================================================

#define MyAppName        "Extraer PDFs"
#ifndef MyAppVersion
  #define MyAppVersion   "0.1.9"
#endif
#define MyAppPublisher   "Flet"
#define MyAppExeName     "extraer_pdfs.exe"
#ifndef MyAppSourceDir
  #define MyAppSourceDir "..\build\windows\x64\runner\Release"
#endif
#define MyAppProgID      "ExtraerPdfs.PdfFile"

[Setup]
AppId={{A3F2C1D0-8B4E-4F9A-B6C2-1D3E5F7A9B0C}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=ExtraerPDFs_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "assocpdf";    Description: "Abrir archivos PDF con {#MyAppName} (agrega a 'Abrir con')"; GroupDescription: "Asociación de archivos:"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}";  Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";      Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; ── ProgID ────────────────────────────────────────────────────────────────────
Root: HKCR; Subkey: "{#MyAppProgID}";                         ValueType: string; ValueName: ""; ValueData: "Documento PDF"; Flags: uninsdeletekey
Root: HKCR; Subkey: "{#MyAppProgID}\DefaultIcon";             ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"

; CRÍTICO: el comando de apertura usa cmd /c set para inyectar la ruta como
; variable de entorno Y pasa %1 como argumento.  Esto garantiza que flet build
; reciba la ruta aunque no propague sys.argv correctamente.
; Las comillas triples (\"\"\" %1 \"\"\") aseguran que rutas con espacios funcionen.
Root: HKCR; Subkey: "{#MyAppProgID}\shell\open\command"; ValueType: string; ValueName: ""; \
  ValueData: "cmd /c set ""EXTRAR_PDF_PATH=%1"" && ""{app}\{#MyAppExeName}"" ""%1"""

; ── Capacidades (modo moderno Windows) ────────────────────────────────────────
Root: HKLM; Subkey: "Software\{#MyAppName}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName";        ValueData: "{#MyAppName}"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Visualiza, extrae texto y aplica OCR a archivos PDF"
Root: HKLM; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyAppProgID}"
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\{#MyAppName}\Capabilities"

; ── Agregar a "Abrir con" ─────────────────────────────────────────────────────
Root: HKCR; Subkey: ".pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgID}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocpdf

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent
