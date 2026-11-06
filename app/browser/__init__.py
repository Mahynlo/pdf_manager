"""La app en un navegador: el mismo backend, en Python compilado a wasm (Pyodide) dentro de un Web Worker.

- :mod:`app.browser.main`: lo que llama el worker (``app/ui/src/lib/browser/worker.ts``).
- :mod:`app.browser.host`: la implementación de :class:`app.backend.host.Host` para el navegador.
- :mod:`app.browser.background`: hilos, que Pyodide no tiene.
- :mod:`app.browser.files`: los PDF del usuario en el sistema de archivos virtual.
- :mod:`app.browser.onnx`: el ``onnxruntime`` del OCR, sobre onnxruntime-web.

Ver ``docs/web/navegador.md``.
"""
