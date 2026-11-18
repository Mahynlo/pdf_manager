# Project Guidelines

## Stack And Scope
- Desktop app: Svelte 5 + TypeScript UI (`app/ui`) in a pywebview/WebView2 window, with a Python backend.
- All PDF work uses PDFium: EmbedPDF (WebAssembly) in the window and `pypdfium2` in Python.
- Do not add PyMuPDF or anything based on MuPDF: it is AGPL.
- Preserve Spanish UI copy unless a task explicitly asks for another language. UI texts live in `app/ui/src/texts/es/`.

## Architecture
- `app/backend/services/`: services exposed to the UI as `"service.method"`, marked with `@exposed`.
- `src/pdf_core/`: PDF logic without any interface. `pdf.py` is the only module that may touch `pypdfium2`:
  PDFium is not thread-safe and everything goes through its lock.
- What stock PDFium cannot do (redact, encrypt, write bookmarks) goes through `Host.run_engine`, which runs it in
  EmbedPDF's engine in the window (`app/ui/src/lib/engine-tasks.ts`).
- Details: `docs/web/arquitectura.md`, `docs/web/embedpdf.md` and `docs/web/modulos-python.md`.

## Build And Run
- Run from the project root: `uv run python -m app.main` (add `--dev` for Vite with hot reload).
- Tests: `uv run pytest tests`. In `app/ui`: `pnpm check` and `pnpm build`; run both, each catches different errors.
- Installer: `.\installer\web\build.ps1`.
