# Versión Qt (PySide6)

Fue un intento de usar una tecnología de escritorio con mejor rendimiento. Como la app tiene que
funcionar con tecnología web, no se llevará a producción.

Hoy es la **referencia** de funciones y aspecto para la versión web:
[../web/paridad.md](../web/paridad.md) lista lo que falta migrar. Cuando no quede nada, se retira de
la rama (ver [../web/modulos-python.md](../web/modulos-python.md#plan-de-retirada)).

```
uv run python src_qt/main.py     # arrancar
```

| Documento | Contenido |
|---|---|
| [arquitectura.md](arquitectura.md) | Organización de `src_qt/`, reglas y cómo añadir una herramienta |

La lógica sin interfaz que comparte con la web está en `src/pdf_core/`. Qt la importa por las rutas
antiguas (`pdf_merge.engine`, `recent_files`…), que son alias de esos módulos.
