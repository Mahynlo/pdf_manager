export type RecentFile = { name: string; path: string }

export type ExtractPayload = {
  referencePath?: string | null
  referencePages?: string
  hintPages?: string
  keywords?: string
  targetPaths: string[]
  destinationDir?: string | null
}

export type ExtractLogEntry = {
  level: 'info' | 'warn' | 'error' | 'success'
  text: string
}

export type ExtractResult = {
  summary: string
  outputPath?: string | null
  log: ExtractLogEntry[]
}

export type MergePayload = {
  paths: string[]
  outputPath?: string | null
}

export type MergeResult = {
  outputPath?: string | null
  message: string
}

export type OpenPdfResult = {
  name: string
  path: string
  dataUrl: string
}

type PyWebviewApi = {
  get_recent_files: () => Promise<RecentFile[]>
  open_pdf: (path: string) => Promise<OpenPdfResult>
  pick_files: (options: { multiple: boolean; title: string }) => Promise<string[]>
  pick_directory: (title: string) => Promise<string | null>
  extract_pdf: (payload: ExtractPayload) => Promise<ExtractResult>
  merge_pdfs: (payload: MergePayload) => Promise<MergeResult>
}

function getApi(): PyWebviewApi | null {
  const anyWindow = window as typeof window & { pywebview?: { api: PyWebviewApi } }
  return anyWindow.pywebview?.api ?? null
}

export async function getRecentFiles(): Promise<RecentFile[]> {
  const api = getApi()
  if (!api) {
    return []
  }
  return api.get_recent_files()
}

export async function openPdf(path: string): Promise<OpenPdfResult | null> {
  const api = getApi()
  if (!api) {
    return null
  }
  return api.open_pdf(path)
}

export async function pickFiles(options: { multiple: boolean; title: string }): Promise<string[]> {
  const api = getApi()
  if (!api) {
    return []
  }
  return api.pick_files(options)
}

export async function pickDirectory(title: string): Promise<string | null> {
  const api = getApi()
  if (!api) {
    return null
  }
  return api.pick_directory(title)
}

export async function extractPdf(payload: ExtractPayload): Promise<ExtractResult | null> {
  const api = getApi()
  if (!api) {
    return null
  }
  return api.extract_pdf(payload)
}

export async function mergePdfs(payload: MergePayload): Promise<MergeResult | null> {
  const api = getApi()
  if (!api) {
    return null
  }
  return api.merge_pdfs(payload)
}
