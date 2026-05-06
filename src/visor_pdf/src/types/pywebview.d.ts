export {}

declare global {
  interface Window {
    pywebview?: {
      api: {
        get_recent_files: () => Promise<{ name: string; path: string }[]>
        open_pdf: (path: string) => Promise<{ name: string; path: string; dataUrl: string }>
        pick_files: (options: { multiple: boolean; title: string }) => Promise<string[]>
        pick_directory: (title: string) => Promise<string | null>
        extract_pdf: (payload: {
          referencePath?: string | null
          referencePages?: string
          hintPages?: string
          keywords?: string
          targetPaths: string[]
          destinationDir?: string | null
        }) => Promise<{ summary: string; outputPath?: string | null; log: { level: string; text: string }[] }>
        merge_pdfs: (payload: {
          paths: string[]
          outputPath?: string | null
        }) => Promise<{ outputPath?: string | null; message: string }>
      }
    }
  }
}
