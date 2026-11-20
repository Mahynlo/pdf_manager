; ============================================================
;  Extraer PDFs (versión web) - instalador Inno Setup
;  Lo compila installer\web\build.ps1; a mano:
;    ISCC.exe /DMyAppVersion=x.y.z /DMyAppSourceDir=dist\web\ExtraerPDFs installer\web\setup.iss
;
;  Convive con una instalación de la versión Flet (otro AppId, carpeta y ProgID). Para
;  que la sustituya al instalarse, usar su AppId: {A3F2C1D0-8B4E-4F9A-B6C2-1D3E5F7A9B0C}.
;
;  Los modelos de OCR son un componente aparte, marcado por defecto. Sin él, la app los
;  descarga la primera vez que se usa el OCR (src/pdf_core/ocr/models.py).
;  Las imágenes del asistente (images\) las genera installer\web\make_images.py.
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
#define MyAppURL         "https://github.com/Mahynlo/pdf_manager"
; Donde PyInstaller deja los modelos dentro de la app (build.ps1: --add-data ...;assets\ocr_models)
#define OcrModelsDir     "_internal\assets\ocr_models"

[Setup]
; GUID propio de la versión web - no cambiar después del primer release
AppId={{6E0B7C1A-4D52-4C8F-9E7B-2F1A3C5D7E90}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
UninstallDisplayName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName} Web
DefaultGroupName={#MyAppName}
SetupIconFile=..\..\launcher\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\..\dist
OutputBaseFilename=ExtraerPDFs_Web_Setup_{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Imágenes propias (100 % y 200 % de escala; Inno Setup elige la que encaja con la pantalla)
WizardImageFile=images\wizard.bmp,images\wizard@2x.bmp
WizardSmallImageFile=images\wizard-small.bmp,images\wizard-small@2x.bmp
; El estilo moderno se salta la bienvenida; se muestra, con la imagen y qué se instala
DisableWelcomePage=no
ChangesAssociations=yes
PrivilegesRequired=admin
; La ventana usa WebView2, que ya viene con Windows 10 (actualizado) y 11.
MinVersion=10.0

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
#if Pos("beta", MyAppVersion) > 0
WelcomeLabel2=Se instalará [name/ver] en el equipo.%n%nVisualiza, anota, censura, combina y protege archivos PDF, y reconoce el texto de los escaneados (OCR).%n%nEsta es una versión de pruebas (beta): si algo falla, avísanos en GitHub. Para trabajo importante, guarda una copia de tus PDF antes de editarlos.
#else
WelcomeLabel2=Se instalará [name/ver] en el equipo.%n%nVisualiza, anota, censura, combina y protege archivos PDF, y reconoce el texto de los escaneados (OCR).
#endif
SelectComponentsLabel2=Elige qué instalar. Los modelos de OCR permiten reconocer texto sin conexión; si no los instalas, se descargarán de internet (unos 38 MB) la primera vez que uses el OCR.

[Types]
Name: "full";    Description: "Completa (recomendada): incluye los modelos de OCR"
Name: "compact"; Description: "Compacta: los modelos de OCR se descargan al usarlo por primera vez"
Name: "custom";  Description: "Personalizada"; Flags: iscustom

[Components]
Name: "app"; Description: "{#MyAppName}";                                Types: full compact custom; Flags: fixed
Name: "ocr"; Description: "Modelos de OCR (reconocer texto sin conexión)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "assocpdf";    Description: "Abrir archivos PDF con {#MyAppName} (agrega a 'Abrir con')"; GroupDescription: "Asociación de archivos:"

[Files]
; La app sin los modelos de OCR (los diccionarios *.txt, pequeños, sí van siempre)
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Excludes: "{#OcrModelsDir}\*.onnx"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: app
Source: "{#MyAppSourceDir}\{#OcrModelsDir}\*.onnx"; DestDir: "{app}\{#OcrModelsDir}"; Flags: ignoreversion; Components: ocr

[InstallDelete]
; Al reinstalar sin el componente, se quitan los modelos de una instalación anterior completa
Type: files; Name: "{app}\{#OcrModelsDir}\*.onnx"; Components: not ocr

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
