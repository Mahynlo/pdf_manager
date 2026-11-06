// Los archivos del usuario en el navegador. Python trabaja con rutas virtuales (/files/…); aquí se
// recuerda a qué archivo real corresponde cada una.
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

/** Archivo elegido: su ruta virtual y su contenido. */
export interface Picked {
  path: string;
  file: File;
}

const TYPES: Record<string, PickerType> = {
  pdf: { description: 'Archivos PDF', accept: { 'application/pdf': ['.pdf'] } },
  txt: { description: 'Archivos de texto', accept: { 'text/plain': ['.txt'] } },
};

const handles = new Map<string, FileHandle>();
const folders = new Map<string, FolderHandle>();
let folderCount = 0;

const newFolder = () => `/files/${++folderCount}`;
const isPdf = (name: string) => name.toLowerCase().endsWith('.pdf');
const cancelled = (err: unknown) => (err as Error).name === 'AbortError';

/** Da una ruta a `file` y recuerda su archivo real, si lo hay. */
function adopt(file: File, handle?: FileHandle): Picked {
  const path = `${newFolder()}/${file.name}`;
  if (handle) handles.set(path, handle);
  return { path, file };
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

export async function pickPdfs(multiple: boolean): Promise<Picked[]> {
  if (window.showOpenFilePicker) {
    try {
      const chosen = await window.showOpenFilePicker({ multiple, types: [TYPES.pdf] });
      return Promise.all(chosen.map(async (handle) => adopt(await handle.getFile(), handle)));
    } catch (err) {
      if (cancelled(err)) return [];
    }
  }
  const files = await chooseFiles((input) => {
    input.accept = '.pdf,application/pdf';
    input.multiple = multiple;
  });
  return files.map((file) => adopt(file));
}

/** PDF soltados en la ventana. Hay que llamarla durante el evento: luego `dataTransfer` queda vacío. */
export async function droppedPdfs(transfer: DataTransfer): Promise<Picked[]> {
  const items = [...transfer.items].filter((item) => item.kind === 'file');
  const entries = items.map((item) => ({ file: item.getAsFile(), handle: item.getAsFileSystemHandle?.() }));
  const picked: Picked[] = [];
  for (const { file, handle } of entries) {
    if (!file || !isPdf(file.name)) continue;
    const real = await handle?.catch(() => null);
    picked.push(adopt(file, real?.kind === 'file' ? real as FileHandle : undefined));
  }
  return picked;
}

async function readFolder(folder: FileSystemDirectoryHandle & { values: FolderHandle['values'] }, path: string, found: Picked[]): Promise<void> {
  for await (const entry of folder.values()) {
    if (entry.kind === 'directory') await readFolder(entry as FolderHandle, `${path}/${entry.name}`, found);
    else if (isPdf(entry.name)) found.push({ path: `${path}/${entry.name}`, file: await (entry as FileSystemFileHandle).getFile() });
  }
}

/**
 * Elige una carpeta: su ruta y los PDF que tiene. `null` si se cancela. Con `output`, una donde
 * escribir: sin File System Access no hay dónde elegir y lo que se escriba se descargará.
 */
export async function pickFolder(output: boolean): Promise<{ path: string; files: Picked[] } | null> {
  const path = newFolder();
  if (window.showDirectoryPicker) {
    try {
      const folder = await window.showDirectoryPicker({ mode: 'readwrite' });
      const files: Picked[] = [];
      if (!output) await readFolder(folder, path, files);
      folders.set(path, folder);
      return { path, files };
    } catch (err) {
      if (cancelled(err)) return null;
    }
  }
  if (output) return { path, files: [] };
  const chosen = await chooseFiles((input) => {
    input.webkitdirectory = true;
  });
  if (!chosen.length) return null;
  const files = chosen.filter((file) => isPdf(file.name))
    .map((file) => ({ path: `${path}/${file.webkitRelativePath.split('/').slice(1).join('/')}`, file }));
  return { path, files };
}

/** Dónde guardar: una ruta nueva, unida al archivo que elija el usuario si el navegador deja elegir. */
export async function pickSave(name: string, kind: string): Promise<string | null> {
  const path = `${newFolder()}/${name}`;
  if (!window.showSaveFilePicker) return path;
  try {
    const handle = await window.showSaveFilePicker({ suggestedName: name, types: [TYPES[kind]] });
    const chosen = `${newFolder()}/${handle.name}`;
    handles.set(chosen, handle);
    return chosen;
  } catch (err) {
    return cancelled(err) ? null : path;
  }
}

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

/** Lleva al archivo real lo que escribió Python en `path`; si no se puede, lo descarga. */
export async function writeBack(path: string, data: Uint8Array<ArrayBuffer>): Promise<void> {
  try {
    const handle = handles.get(path) ?? await inFolder(path);
    if (handle && await allowed(handle)) {
      const writable = await handle.createWritable();
      await writable.write(data);
      await writable.close();
      return;
    }
  } catch (err) {
    console.error('No se pudo escribir en el archivo', err);
  }
  download(path, data);
}
