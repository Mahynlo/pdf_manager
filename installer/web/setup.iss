; ============================================================
;  Extraer PDFs (versión web) - instalador Inno Setup
;  Lo compila installer\web\build.ps1; a mano:
;    ISCC.exe /DMyAppVersion=x.y.z /DMyAppSourceDir=dist\web\ExtraerPDFs installer\web\setup.iss
;
;  Convive con la versión Flet (otro AppId, carpeta y ProgID) mientras dure la
;  transición. Para que sustituya a la de Flet al instalarse, usar el AppId de
;  installer\setup.iss.
; ============================================================

#define MyAppName        "Extraer PDFs"
#ifndef MyAppVersion
  #define MyAppVersion   "0.1.28"
#endif
#define MyAppPublisher   "MHNL"
#define MyAppExeName     "ExtraerPDFs.exe"
#ifndef MyAppSourceDir
  #define MyAppSourceDir "..\..\dist\web\ExtraerPDFs"
#endif
#define MyAppProgID      "ExtraerPdfs.Web.PdfFile"

[Setup]
; GUID propio de la versión web - no cambiar después del primer release
AppId={{6E0B7C1A-4D52-4C8F-9E7B-2F1A3C5D7E90}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName} Web
DefaultGroupName={#MyAppName}
SetupIconFile=..\..\launcher\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\..\dist
OutputBaseFilename=ExtraerPDFs_Web_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
PrivilegesRequired=admin
; La ventana usa WebView2, que ya viene con Windows 10 (actualizado) y 11.
MinVersion=10.0

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "assocpdf";    Description: "Abrir archivos PDF con {#MyAppName} (agrega a 'Abrir con')"; GroupDescription: "Asociación de archivos:"

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";             Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";     Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; ── ProgID: el exe recibe la ruta como argumento (no necesita launcher) ─────
Root: HKCR; Subkey: "{#MyAppProgID}";                      ValueType: string; ValueName: ""; ValueData: "Documento PDF (Extraer PDFs)"; Flags: uninsdeletekey
Root: HKCR; Subkey: "{#MyAppProgID}\DefaultIcon";          ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "{#MyAppProgID}\shell\open\command";   ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

; ── «Abrir con» → «Buscar otra aplicación» ─────────────────────────────────
Root: HKCR; Subkey: "Applications\{#MyAppExeName}";                        ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Applications\{#MyAppExeName}\DefaultIcon";            ValueType: string; ValueName: "";                ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "Applications\{#MyAppExeName}\shell\open\command";     ValueType: string; ValueName: "";                ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCR; Subkey: "Applications\{#MyAppExeName}\SupportedTypes";         ValueType: string; ValueName: ".pdf";            ValueData: ""

; ── Capacidades (Configuración → Aplicaciones predeterminadas) ─────────────
Root: HKLM; Subkey: "Software\{#MyAppName} Web";                                        Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\{#MyAppName} Web\Capabilities";   ValueType: string; ValueName: "ApplicationName";        ValueData: "{#MyAppName}"
Root: HKLM; Subkey: "Software\{#MyAppName} Web\Capabilities";   ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Visualiza, anota, censura, combina y aplica OCR a archivos PDF"
Root: HKLM; Subkey: "Software\{#MyAppName} Web\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyAppProgID}"
Root: HKLM; Subkey: "Software\RegisteredApplications";          ValueType: string; ValueName: "{#MyAppName} Web";       ValueData: "Software\{#MyAppName} Web\Capabilities"; Flags: uninsdeletevalue

; ── Agrega la app a «Abrir con» para .pdf (no cambia el programa predeterminado) ──
Root: HKCR; Subkey: ".pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgID}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocpdf

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent
