# Documentación de PDF Manager

El proyecto tiene tres versiones de la interfaz. La documentación está separada por versión.

| Versión | Código | Estado | Documentación |
|---|---|---|---|
| **Web** (HTML/CSS/JS + Python con pywebview) | `app/` + `src/pdf_core/` | **En desarrollo. Será la definitiva** y sustituirá a Flet en producción | [web/](web/README.md) |
| **Flet** | `src/` (salvo `src/pdf_core/`) | **En producción** hasta que la web la sustituya; después se mantiene un tiempo por compatibilidad | [flet/](flet/README.md) |
| **Qt** (PySide6) | `src_qt/` | **Referencia** de funciones y aspecto mientras se migra a la web. Al terminar la migración se retira de la rama | [qt/](qt/README.md) |

## Dónde está cada cosa

```
app/              versión web: backend Python (servicios) + interfaz en Svelte (app/ui)
src/pdf_core/     lógica de PDF sin interfaz. Es todo el Python de src/ que usa la web
src/              versión Flet (interfaz) y módulos de compatibilidad con rutas antiguas
src_qt/           versión Qt (se retirará)
docs/web|flet|qt  documentación de cada versión
docs/ayuda/       manuales que muestra la pestaña Ayuda
tests/            pruebas de las tres versiones (test_app_backend.py y test_web_architecture.py son de la web)
```

El mapa de los módulos de Python de la web, sus reglas y el plan para retirar Qt y Flet están en
[web/modulos-python.md](web/modulos-python.md).
