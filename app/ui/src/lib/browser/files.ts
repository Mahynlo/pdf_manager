// Los archivos del usuario en el navegador. Python trabaja con rutas virtuales (/files/…); aquí se
// recuerda qué archivo es cada una, y se tiene su contenido.
//
// Python pide el contenido cuando lo necesita (`readFiles`): las herramientas lo copian a su
// sistema de archivos al elegirlo; el visor no guarda copia, lo abre desde aquí (`fileUrl`) y lo que
// guarda vuelve aquí (`writeFile`). Ver app/browser/host.py.
//
// Chrome y Edge dejan abrir y guardar sobre el archivo real (File System Access). Firefox y Safari
// no: se abre con el selector de archivos y lo que se guarda se descarga.

interface PickerType {
  description: string;
  accept: Record<string, string[]>;
}

interface WritableHandle {
  queryPermission(options: { mode: 'readwrite' }): Promise<PermissionState>;
  requestPermission(options: { mode: 'readwrite' }): Promise<PermissionState>;
}

type FileHandle = FileSystemFileHandle & WritableHandle;
type FolderHandle = FileSystemDirectoryHandle & WritableHandle & {
  values(): AsyncIterable<FileSystemFileHandle | FileSystemDirectoryHandle>;
};

declare global {
  interface Window {
    showOpenFilePicker?(options: { multiple: boolean; types: PickerType[] }): Promise<FileHandle[]>;
    showSaveFilePicker?(options: { suggestedName: string; types: PickerType[] }): Promise<FileHandle>;
    showDirectoryPicker?(options: { mode: 'readwrite' }): Promise<FolderHandle>;
  }
  interface DataTransferItem {
    getAsFileSystemHandle?(): Promise<FileSystemHandle | null>;
  }
}

/**
 * Un archivo del usuario. Con `handle` se lee del archivo real (y se escribe en él, si es un
 * `FileHandle`); `content` es lo que hay sin archivo real, o lo último escrito mientras se guarda.
 */
interface UserFile {
  handle?: FileSystemFileHandle;
  content?: Blob;
}

/** Contenido de un archivo, para Python. */
export interface FileData {
  path: string;
  data: Uint8Array;
}

const TYPES: Record<string, PickerType> = {
  pdf: { description: 'Archivos PDF', accept: { 'application/pdf': ['.pdf'] } },
  txt: { description: 'Archivos de texto', accept: { 'text/plain': ['.txt'] } },
};
const URL_LIFETIME_MS = 120_000;

const files = new Map<string, UserFile>();
const folders = new Map<string, FolderHandle>();
let folderCount = 0;

const newFolder = () => `/files/${++folderCount}`;
const isPdf = (name: string) => name.toLowerCase().endsWith('.pdf');
const cancelled = (err: unknown) => (err as Error).name === 'AbortError';
const writable = (handle: FileSystemFileHandle): handle is FileHandle => 'requestPermission' in handle;

/** Da una ruta a `file` (en una carpeta nueva) y lo recuerda. */
function adopt(file: File, handle?: FileSystemFileHandle): string {
  const path = `${newFolder()}/${file.name}`;
  files.set(path, handle ? { handle } : { content: file });
  return path;
}

/** Selector de archivos clásico (lo hay en todos los navegadores). */
function chooseFiles(setup: (input: HTMLInputElement) => void): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    setup(input);
    input.addEventListener('change', () => resolve([...input.files!]));
    input.addEventListener('cancel', () => resolve([]));
    input.click();
  });
}

/** Elige PDF: sus rutas. */
export async function pickPdfs(multiple: boolean): Promise<string[]> {
  if (window.showOpenFilePicker) {
    try {
      const chosen = await window.showOpenFilePicker({ multiple, types: [TYPES.pdf] });
      return Promise.all(chosen.map(async (handle) => adopt(await handle.getFile(), handle)));
    } catch (err) {
      if (cancelled(err)) return [];
    }
  }
  const chosen = await chooseFiles((input) => {
    input.accept = '.pdf,application/pdf';
    input.multiple = multiple;
  });
  return chosen.map((file) => adopt(file));
}

/** PDF soltados en la ventana: sus rutas. Hay que llamarla durante el evento: luego `dataTransfer` queda vacío. */
export async function droppedPdfs(transfer: DataTransfer): Promise<string[]> {
  const items = [...transfer.items].filter((item) => item.kind === 'file');
  const entries = items.map((item) => ({ file: item.getAsFile(), handle: item.getAsFileSystemHandle?.() }));
  const paths: string[] = [];
  for (const { file, handle } of entries) {
    if (!file || !isPdf(file.name)) continue;
    const real = await handle?.catch(() => null);
    paths.push(adopt(file, real?.kind === 'file' ? real as FileSystemFileHandle : undefined));
  }
  return paths;
}

async function readFolder(folder: FileSystemDirectoryHandle & { values: FolderHandle['values'] }, path: string, found: string[]): Promise<void> {
  for await (const entry of folder.values()) {
    const inside = `${path}/${entry.name}`;
    if (entry.kind === 'directory') {
      await readFolder(entry as FolderHandle, inside, found);
    } else if (isPdf(entry.name)) {
      files.set(inside, { handle: entry as FileSystemFileHandle });
      found.push(inside);
    }
  }
}

/**
 * Elige una carpeta: su ruta y las de los PDF que tiene. `null` si se cancela. Con `output`, una
 * donde escribir: sin File System Access no hay dónde elegir y lo que se escriba se descargará.
 */
export async function pickFolder(output: boolean): Promise<{ path: string; files: string[] } | null> {
  const path = newFolder();
  if (window.showDirectoryPicker) {
    try {
      const folder = await window.showDirectoryPicker({ mode: 'readwrite' });
      const found: string[] = [];
      if (!output) await readFolder(folder, path, found);
      folders.set(path, folder);
      return { path, files: found };
    } catch (err) {
      if (cancelled(err)) return null;
    }
  }
  if (output) return { path, files: [] };
  const chosen = await chooseFiles((input) => {
    input.webkitdirectory = true;
  });
  if (!chosen.length) return null;
  const found = chosen.filter((file) => isPdf(file.name)).map((file) => {
    const inside = `${path}/${file.webkitRelativePath.split('/').slice(1).join('/')}`;
    files.set(inside, { content: file });
    return inside;
  });
  return { path, files: found };
}

/** Dónde guardar: una ruta nueva, unida al archivo que elija el usuario si el navegador deja elegir. */
export async function pickSave(name: string, kind: string): Promise<string | null> {
  const path = `${newFolder()}/${name}`;
  if (!window.showSaveFilePicker) return path;
  try {
    const handle = await window.showSaveFilePicker({ suggestedName: name, types: [TYPES[kind]] });
    const chosen = `${newFolder()}/${handle.name}`;
    files.set(chosen, { handle });
    return chosen;
  } catch (err) {
    return cancelled(err) ? null : path;
  }
}

// ── Contenido ──────────────────────────────────────────────────────────────

/** El contenido de `path`; `null` si no es un archivo que tenga la ventana. */
async function contentOf(path: string): Promise<Blob | null> {
  const file = files.get(path);
  if (!file) return null;
  return file.content ?? await file.handle!.getFile();
}

/** El contenido de los archivos `paths` que tiene la ventana (los demás no vienen). */
export async function readFiles(paths: string[]): Promise<FileData[]> {
  const found: FileData[] = [];
  for (const path of paths) {
    const content = await contentOf(path);
    if (content) found.push({ path, data: new Uint8Array(await content.arrayBuffer()) });
  }
  return found;
}

/** El tamaño de `path` en bytes; `null` si no lo tiene la ventana. */
export async function fileSize(path: string): Promise<number | null> {
  return (await contentOf(path))?.size ?? null;
}

/** Una URL `blob:` de `path`, sin copiarlo (dura un rato); `null` si no lo tiene la ventana. */
export async function fileUrl(path: string): Promise<string | null> {
  const content = await contentOf(path);
  if (!content) return null;
  const url = URL.createObjectURL(content);
  setTimeout(() => URL.revokeObjectURL(url), URL_LIFETIME_MS);
  return url;
}

// ── Guardar ────────────────────────────────────────────────────────────────

async function allowed(handle: WritableHandle): Promise<boolean> {
  const mode = { mode: 'readwrite' } as const;
  return await handle.queryPermission(mode) === 'granted' || await handle.requestPermission(mode) === 'granted';
}

/** El archivo real de `path` dentro de una carpeta elegida, creándolo si hace falta. */
async function inFolder(path: string): Promise<FileHandle | null> {
  for (const [root, folder] of folders) {
    if (!path.startsWith(`${root}/`)) continue;
    const parts = path.slice(root.length + 1).split('/');
    let current: FileSystemDirectoryHandle = folder;
    for (const part of parts.slice(0, -1)) current = await current.getDirectoryHandle(part, { create: true });
    return await current.getFileHandle(parts.at(-1)!, { create: true }) as FileHandle;
  }
  return null;
}

function download(path: string, data: Uint8Array<ArrayBuffer>): void {
  const url = URL.createObjectURL(new Blob([data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = path.split('/').at(-1)!;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/**
 * Lleva al archivo real lo que escribió Python en su copia de `path`; si no se puede, lo descarga.
 * Si la ventana tiene ese archivo, se queda con lo nuevo.
 */
export async function writeBack(path: string, data: Uint8Array<ArrayBuffer>): Promise<void> {
  const file = files.get(path);
  const content = new Blob([data]);
  if (file) file.content = content; // ya, antes de esperar: lo que Python pida después es lo nuevo
  try {
    const handle = file?.handle ?? await inFolder(path);
    if (handle && writable(handle) && await allowed(handle)) {
      const output = await handle.createWritable();
      await output.write(data);
      await output.close();
      if (file?.content === content) file.content = undefined; // ya está en el archivo real
      return;
    }
  } catch (err) {
    console.error('No se pudo escribir en el archivo', err);
  }
  download(path, data);
}

/** Escribe `path`, del que Python no tiene copia (un documento del visor): la ventana se lo queda. */
export function writeFile(path: string, data: Uint8Array<ArrayBuffer>): Promise<void> {
  if (!files.has(path)) files.set(path, {});
  return writeBack(path, data);
}
