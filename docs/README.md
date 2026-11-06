# Documentación de PDF Manager

La aplicación es la **versión web**: interfaz en Svelte dentro de una ventana de escritorio (pywebview
y WebView2) y backend en Python. Su documentación está en [web/](web/README.md).

Las versiones anteriores se retiraron de esta rama: **Flet** (la 0.1.28 fue la última, en la rama
`Flet`) y **Qt** (PySide6, en la rama local `feature/html-ui`).

## Dónde está cada cosa

```
app/              backend Python (servicios) + interfaz en Svelte (app/ui)
app/browser/      lo propio de la versión de navegador (web/navegador.md)
src/pdf_core/     lógica de PDF sin interfaz
src/assets/       manuales de ayuda y modelos de OCR
docs/web/         documentación técnica
docs/ayuda/       manuales que muestra la pestaña Ayuda
tests/            pruebas
```

El mapa de los módulos de Python y sus reglas están en [web/modulos-python.md](web/modulos-python.md).
