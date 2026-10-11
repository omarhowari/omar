/* TDA.exe - tiny launcher that embeds the bundled Python runtime (python313.dll)
 * located next to it and runs app\main.py.  Running in-process means the
 * firewall prompt and Task Manager show "TDA", not "python". */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

typedef int (*PyMainFn)(int, wchar_t **);

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show)
{
    wchar_t dir[MAX_PATH], dll[MAX_PATH], script[MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    SetCurrentDirectoryW(dir);
    SetDllDirectoryW(dir);

    /* GUI process: drop any unusable inherited std handle so Python sets
       sys.stdout etc. to None instead of aborting at startup. */
    DWORD ids[3] = {STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE};
    for (int i = 0; i < 3; i++) {
        HANDLE h = GetStdHandle(ids[i]);
        if (h == NULL || h == INVALID_HANDLE_VALUE) continue;
        SetLastError(0);
        DWORD type = GetFileType(h);
        if (type == FILE_TYPE_UNKNOWN || type == FILE_TYPE_CHAR) SetStdHandle(ids[i], NULL);
    }

    swprintf(dll, MAX_PATH, L"%ls\\python313.dll", dir);
    swprintf(script, MAX_PATH, L"%ls\\app\\main.py", dir);

    HMODULE py = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!py) {
        MessageBoxW(NULL, L"python313.dll is missing. Please reinstall TDA.", L"TDA", MB_ICONERROR);
        return 1;
    }
    PyMainFn py_main = (PyMainFn)GetProcAddress(py, "Py_Main");
    if (!py_main) {
        MessageBoxW(NULL, L"Py_Main not found in python313.dll.", L"TDA", MB_ICONERROR);
        return 1;
    }

    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    wchar_t **args = (wchar_t **)HeapAlloc(GetProcessHeap(), 0, sizeof(wchar_t *) * (argc + 4));
    int n = 0;
    args[n++] = argv[0];
    args[n++] = L"-s";          /* ignore user site-packages */
    args[n++] = L"-X";
    args[n++] = L"utf8";
    /* we need the script as an argument before the user args */
    wchar_t **full = (wchar_t **)HeapAlloc(GetProcessHeap(), 0, sizeof(wchar_t *) * (argc + 6));
    int m = 0;
    for (int i = 0; i < n; i++) full[m++] = args[i];
    full[m++] = script;
    for (int i = 1; i < argc; i++) full[m++] = argv[i];
    full[m] = NULL;
    return py_main(m, full);
}
