# Project Guidelines

## Stack And Scope
- This is a Python app built with Flet and PyMuPDF.
- Keep changes focused on the existing app behavior: open PDFs in tabs, navigate pages, annotate, and save.
- Preserve Spanish UI copy unless a task explicitly asks for another language.

## Architecture
- App entry point is `src/main.py` with `main(page: ft.Page)` and top-level tab/file-picker wiring.
- One open PDF is represented by `PDFViewerTab` in `src/pdf_viewer/viewer.py`.
- Annotation tool state and operations live in `src/pdf_viewer/annotations.py` (`AnnotationManager`, `Tool`).
- Rendering and coordinate conversion live in `src/pdf_viewer/renderer.py` (`render_page`, `display_to_pdf`).
- Keep module boundaries intact: avoid moving rendering logic into UI files or annotation logic into `main.py`.

## Build And Run
- Preferred run command: `uv run flet run`
- Web mode: `uv run flet run --web`
- Alternative runner: `poetry run flet run`
- Packaging commands are documented in `README.md` and `CLAUDE.md`.

## Coding Conventions
- Follow imperative Flet patterns already used in the repo:
  - mutate control/state fields, then call `.update()` or `page.update()`.
  - keep UI state in instance attributes and callback closures.
- Keep existing naming style:
  - internal helpers prefixed with `_`.
  - module-level constants in upper snake case.
- Avoid adding heavy abstractions unless requested; current design is class-based and direct.

## PDF And Annotation Safety
- Always convert UI pixel coordinates to PDF points with `display_to_pdf()` before applying PDF operations.
- `PDFViewerTab` owns a `fitz.Document`; ensure `close()` is called when a tab is closed.
- Respect `BASE_SCALE` and `ZOOM_LEVELS` from `src/pdf_viewer/renderer.py` when changing render/zoom behavior.
- Keep undo/history behavior consistent with `AnnotationManager._history`.

## Documentation Links
- Use `CLAUDE.md` as the primary agent-oriented technical reference for this workspace.
- Use `README.md` for run/build usage and packaging links.
- Prefer linking to those docs instead of duplicating long instructions in code comments or new docs.
