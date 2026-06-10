/* ============================================================================
 *  launcher.exe  —  Puente "Abrir con" para Extraer PDFs
 *
 *  POR QUE EXISTE:
 *    El exe empaquetado por `flet build windows` (extraer_pdfs.exe) NO arranca
 *    el backend de Python si se le pasa CUALQUIER argumento de linea de comandos
 *    (ni una ruta posicional ni --dart-entrypoint-args): el runner de Flutter se
 *    rompe y solo queda una ventana en blanco. Por eso "Abrir con" no funciona si
 *    el registro invoca   extraer_pdfs.exe "%1".
 *
 *  QUE HACE:
 *    Windows invoca   launcher.exe "C:\ruta\archivo.pdf".  Como es un exe nativo
 *    normal, recibe el argumento sin problemas y:
 *      1. Intenta reenviar la ruta a la instancia ya abierta por el socket IPC
 *         (127.0.0.1:57423, mismo protocolo que main.py: u32 big-endian con la
 *         longitud + JSON ["ruta"] en UTF-8). Sin parpadeo de ventana.
 *      2. Si no hay instancia, lanza extraer_pdfs.exe SIN argumentos pero con la
 *         ruta en la variable de entorno EXTRAR_PDF_PATH, que main.py si lee.
 *
 *  Compilar:  gcc launcher.c -o launcher.exe -lws2_32 -lshell32 -mwindows -O2 -s
 * ========================================================================== */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <shellapi.h>
#include <stdlib.h>
#include <string.h>

#define IPC_PORT 57423

/* Convierte una cadena wide a UTF-8 recien reservada. *out_len = bytes sin NUL. */
static char *to_utf8(const wchar_t *w, int *out_len)
{
    int len = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
    if (len <= 0)
        return NULL;
    char *buf = (char *)malloc((size_t)len);
    if (!buf)
        return NULL;
    WideCharToMultiByte(CP_UTF8, 0, w, -1, buf, len, NULL, NULL);
    if (out_len)
        *out_len = len - 1; /* descarta el NUL */
    return buf;
}

/* Construye el payload JSON ["ruta"] en UTF-8, escapando \ y ". */
static char *build_json(const wchar_t *path, int *out_len)
{
    int u8len = 0;
    char *u8 = to_utf8(path, &u8len);
    if (!u8)
        return NULL;
    char *json = (char *)malloc((size_t)u8len * 2 + 8); /* peor caso + corchetes */
    if (!json)
    {
        free(u8);
        return NULL;
    }
    int j = 0;
    json[j++] = '[';
    json[j++] = '"';
    for (int i = 0; i < u8len; i++)
    {
        char c = u8[i];
        if (c == '\\' || c == '"')
            json[j++] = '\\';
        json[j++] = c;
    }
    json[j++] = '"';
    json[j++] = ']';
    free(u8);
    if (out_len)
        *out_len = j;
    return json;
}

/* Reenvia el payload al primario. Devuelve 1 si lo entrego completo. */
static int forward(const char *payload, int len)
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
        return 0;

    int ok = 0;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s != INVALID_SOCKET)
    {
        struct sockaddr_in addr;
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_port = htons(IPC_PORT);
        addr.sin_addr.s_addr = inet_addr("127.0.0.1");

        /* En loopback, si no hay servidor connect() falla al instante
         * (WSAECONNREFUSED); no hace falta timeout explicito. */
        if (connect(s, (struct sockaddr *)&addr, sizeof(addr)) == 0)
        {
            unsigned long netlen = htonl((unsigned long)len);
            if (send(s, (const char *)&netlen, 4, 0) == 4)
            {
                int sent = 0;
                while (sent < len)
                {
                    int n = send(s, payload + sent, len - sent, 0);
                    if (n <= 0)
                        break;
                    sent += n;
                }
                if (sent == len)
                    ok = 1;
            }
        }
        closesocket(s);
    }
    WSACleanup();
    return ok;
}

/* Lanza extraer_pdfs.exe (mismo directorio) con la ruta en EXTRAR_PDF_PATH. */
static void launch_app(const wchar_t *path)
{
    wchar_t exe[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH);
    if (n == 0 || n >= MAX_PATH)
        return;

    wchar_t *slash = wcsrchr(exe, L'\\');
    if (slash)
        *(slash + 1) = 0; /* deja el directorio con la barra final */
    if (wcslen(exe) + wcslen(L"extraer_pdfs.exe") >= MAX_PATH)
        return;
    wcscat(exe, L"extraer_pdfs.exe");

    if (path && path[0])
        SetEnvironmentVariableW(L"EXTRAR_PDF_PATH", path);

    /* CreateProcessW necesita un buffer modificable y la ruta entre comillas. */
    wchar_t cmd[MAX_PATH + 4];
    cmd[0] = L'"';
    wcscpy(cmd + 1, exe);
    wcscat(cmd, L"\"");

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si));
    si.cb = sizeof(si);
    memset(&pi, 0, sizeof(pi));

    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
    {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR lpCmd, int nShow)
{
    (void)hInst;
    (void)hPrev;
    (void)lpCmd;
    (void)nShow;

    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    const wchar_t *path = (argv && argc >= 2) ? argv[1] : L"";

    int len = 0;
    char *payload = NULL;
    if (path[0])
    {
        payload = build_json(path, &len);
    }
    else
    {
        /* Sin ruta: solo activar/traer al frente la instancia existente. */
        static const char act[] = "[\"__ACTIVATE__\"]";
        len = (int)(sizeof(act) - 1);
        payload = _strdup(act);
    }

    if (!payload || !forward(payload, len))
        launch_app(path);

    free(payload);
    if (argv)
        LocalFree(argv);
    return 0;
}
