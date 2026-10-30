# Paridad: versión Qt → versión web

Lista de todo lo que hace la versión Qt (`src_qt/`) y su estado en la versión web (`app/`).
Cuando no quede nada pendiente, la versión Qt se puede retirar.

✅ hecho · 🟡 parcial · ⬜ pendiente

## Ventana y sistema

| Función | Estado | Notas |
|---|---|---|
| Pestañas: Inicio fija + una por herramienta, cerrar (×, clic central) | ✅ | |
| Botón de marca con menú (Abrir PDF, herramientas, tema) | ✅ | |
| «+» abre un PDF, lista de pestañas abiertas | ✅ | |
| Tema claro/oscuro recordado, barra de título a juego | ✅ | |
| Atajos Ctrl+O, Ctrl+F4, Ctrl+Tab, Ctrl+Shift+Tab | ✅ | |
| Barra de estado | ✅ | |
| Una pestaña por PDF abierto (visor); el mismo PDF no se abre dos veces | ✅ | Pide la contraseña si hace falta |
| Menú contextual de pestañas (cerrar otras/a la derecha, copiar ruta, abrir carpeta) | ✅ | |
| Arrastrar y soltar PDFs en la ventana | ✅ | Aviso «Suelta los PDF para abrirlos». Probado con un arrastre simulado; el arrastre real desde el Explorador queda por comprobar a mano |
| Instancia única y «Abrir con» de Windows | ✅ | Tubería con nombre (`app/single_instance.py`); probado con dos procesos reales y con el ejecutable. Sin launcher: el exe recibe las rutas. La asociación la registra el instalador |
| Avisar de cambios sin guardar al cerrar (pestaña y ventana); marca ● en la pestaña | ✅ | Al salir también avisa de una extracción en curso, que se cancela si se cierra (`quit_warnings` en `services/__init__.py`) |
| Instalador | 🟡 | `installer/web/build.ps1` (PyInstaller + Inno Setup), ver [instalador.md](instalador.md). El ejecutable (184 MB) funciona, con OCR incluido; falta compilar el instalador (Inno Setup no estaba instalado) |

## Inicio

| Función | Estado | Notas |
|---|---|---|
| Tarjetas de herramientas y «OCR de PDF» | ✅ | |
| Archivos recientes: abrir, quitar, limpiar | ✅ | Mismo archivo de recientes que Qt y Flet |
| Recientes: menú contextual (abrir, ubicación, copiar ruta, quitar) | ✅ | |

## Combinar

| Función | Estado | Notas |
|---|---|---|
| Cargar PDFs y carpetas, contraseñas | ✅ | |
| Selección de páginas, rangos, Todas/Ninguna/Invertir | ✅ | |
| Girar, mover, quitar, ordenar A-Z, invertir orden | ✅ | |
| Vista previa reordenable e intercalable, visor ampliado | ✅ | |
| Marcadores, dúplex, optimizar, destino, progreso | ✅ | |
| Ver PDF combinado / abrir carpeta | ✅ | |

## Seguridad

| Función | Estado | Notas |
|---|---|---|
| Analizar PDF: protección, cifrado, permisos | ✅ | |
| Desbloquear y abrir, guardar sin contraseña | ✅ | El visor recibe la contraseña: no la vuelve a pedir |
| Proteger: niveles rápidos, permisos personalizados, contraseñas usuario/propietario | ✅ | Corrige un fallo de Qt: allí se ignoraban las casillas personalizadas |

## Extraer

| Función | Estado | Notas |
|---|---|---|
| Paso 1: PDF de referencia opcional (con contraseña) y sus páginas | ✅ | |
| Paso 2: palabras clave, preajustes, AND/OR, tildes, mayúsculas, palabras completas, páginas sugeridas | ✅ | |
| Extracción directa por rango numérico | ✅ | |
| Paso 3: PDFs objetivo (archivos y carpetas), carpeta de destino, uno o varios PDFs de salida | ✅ | |
| Trabajo en segundo plano: progreso, cancelación, contraseñas pedidas a mitad del proceso | ✅ | |
| Registro de operación y tabla de coincidencias | ✅ | |
| Ver PDF generado, abrir carpeta | ✅ | |
| Confirmar antes de cerrar con una extracción en curso | ✅ | |
| Liberar el modelo de OCR tras 12 s sin uso | ✅ | |

## Ajustes

| Función | Estado | Notas |
|---|---|---|
| Tema de la aplicación (sincronizado con el botón de la cabecera) | ✅ | |
| Historial de recientes: vaciar | ✅ | Inicio se actualiza al momento |
| Registro de diagnóstico y versión de motores | ✅ | Registro propio de la app: `~/.pdf_manager/app.log` |
| Atajos de teclado | ✅ | Los del visor funcionan a medida que se migran sus funciones |

## Ayuda

| Función | Estado | Notas |
|---|---|---|
| Primeros pasos, herramientas, preguntas frecuentes | ✅ | |
| Documentos (manuales de `src/assets/ayuda`) | ✅ | Ahora también se ven sus imágenes; los enlaces abren el navegador |

## Visor de PDF

| Función | Estado | Notas |
|---|---|---|
| Páginas con carga diferida, zoom (botones, lista, Ctrl+rueda), ajustar al ancho/página, ir a página (Ctrl+G) | ✅ | Resolución según el zoom y la densidad de la pantalla |
| Modos de vista: continuo, doble página, página única (la rueda pasa de página en el borde) | ✅ | |
| Navegación: primera/anterior/siguiente/última, Inicio/Fin, Av/Re Pág, flechas | ✅ | |
| Miniaturas laterales (mostrar/ocultar) e índice (marcadores) en el panel derecho | ✅ | |
| Modo noche, arrastrar para desplazar (mano), propiedades del documento, cerrar documento | ✅ | |
| Mover, duplicar, insertar en blanco, eliminar y extraer páginas (también arrastrando miniaturas) | ✅ | Operaciones en `pdf_core/page_ops.py`, compartidas con Qt. Nuevo: se pueden deshacer y rehacer (Ctrl+Z, Ctrl+Y), también los giros |
| Rotar páginas (90°, 180°, todas) | ✅ | |
| Corregir orientación del escaneo (esta página / todas) | ✅ | Menú ⋮ y botón «Orientar» del panel OCR. Detecta también páginas escaneadas al revés (en Qt el clasificador las daba por buenas): si no está seguro, decide el OCR en las cuatro orientaciones |
| Guardar (Ctrl+S), guardar como (Ctrl+Shift+S), avisar de cambios sin guardar | ✅ | Un PDF cifrado conserva su contraseña al guardar (en Qt se perdía: corregido en `pdf_core`) |
| Herramientas mano y selección de texto; seleccionar arrastrando (también entre páginas), doble clic (palabra), Ctrl+A, copiar (Ctrl+C) | ✅ | Con el complemento Selection de EmbedPDF (texto de PDFium y el de OCR); además, triple clic selecciona la línea. |
| Barra flotante de la selección: copiar, resaltar/subrayar/tachar, enviar a censura, buscar en el documento, buscar en Google, explicar con IA | ✅ | |
| Pestaña «Buscar» (Ctrl+F): mayúsculas, anterior/siguiente (F3 / Shift+F3), resultados con fragmento | ✅ | Con el complemento Search de EmbedPDF. «Aa» distingue mayúsculas de verdad (en Qt no tenía efecto); nuevo: «ab» solo palabras completas; todas las coincidencias marcadas en la página (la actual, más fuerte); los resultados llegan mientras busca y no hay tope (antes, 2000). También encuentra el texto reconocido por OCR |
| Anotaciones: resaltar, subrayar, tachar (herramienta o barra de la selección), rectángulo, círculo, flecha, pluma y dibujo fino, paleta de colores. Nuevas con EmbedPDF: ondulado, indicar y reemplazar texto, línea, polilínea, polígono, marcador, llamada e imagen | ✅ | Con EmbedPDF: se guardan en el PDF; las existentes se ven y se editan con su apariencia original, también en las miniaturas. Las flechas se guardan como flecha (en Qt se perdía la punta) y se respetan las páginas giradas |
| Deshacer/rehacer anotaciones (Ctrl+Z, Ctrl+Y) | ✅ | El mismo Ctrl+Z deshace también las operaciones de página |
| Texto libre (editable en la página, doble clic), notas adhesivas, sellos rápidos y leyendas guardadas (gestor) | ✅ | Leyendas en el mismo archivo que Qt y Flet |
| Puntero de objetos y edición de anotaciones: mover, redimensionar, color, relleno, grosor, tamaño de letra, duplicar (Ctrl+D), orden, borrar (Supr), flechas | ✅ | «Traer al frente» y «Enviar al fondo» en la barra de propiedades (con las imágenes no: no se pueden volver a crear). Nuevo: girar formas y texto, mover los extremos de una flecha. Varias se seleccionan con Ctrl+clic |
| Leyendas y sellos guardados | ✅ | Ver «Texto libre, notas…»; también «Gestionar Leyendas y Sellos…» en el menú ⋮ |
| OCR: página actual, por lotes, área, métricas; copiar y guardar TXT | ✅ | Pestaña «OCR» del panel derecho (botón de la barra). El texto reconocido se puede seleccionar, buscar y exportar; el modelo se libera tras 12 s sin uso. Al girar una página se descarta su OCR (ya no coincide con lo que se ve) |
| Censura: términos, patrones (DNI, correos, tarjetas…), perfiles, vista previa, aplicar | ✅ | Pestaña «Censura»; también desde la barra de la selección y desde «Buscar». Con EmbedPDF, cada coincidencia es una marca en la página que se revisa, se mueve, se borra o se deshace; nuevo: «Marcar» un texto o un área a mano. Incluye el texto de OCR (y al censurar se borran también esas palabras). Un documento censurado solo se guarda como copia (`_censurado.pdf`). «Aa» distingue mayúsculas de verdad (en Qt no tenía efecto en frases) |
| Imprimir: rango, orden inverso, intercalar, vista previa | ✅ | Menú ⋮ y Ctrl+P. Diálogo propio (páginas, subconjunto, orden inverso, orientación automática por página, color, escala y vista previa) y después el diálogo de impresión del sistema (impresora, copias, intercalar, doble cara). Se imprimen también las anotaciones; las páginas las dibuja PDFium (EmbedPDF), como se ven |
| Exportar texto (.txt) y extraer imágenes | ✅ | Las páginas sin texto nativo exportan su texto de OCR |
| Panel de IA: resumen, datos clave, datos sensibles, chat | ✅ | Pestaña «IA» y «Explicar con Agente IA» en la barra de la selección. Con proveedor (Gemini u OpenAI) y clave configurados usa el agente; si no, modo básico con el texto del documento (incluido el de OCR). Los datos sensibles se envían a «Censura». En Qt el agente nunca llegaba a crearse (le faltaba la clave) y siempre respondía en modo básico. **Las dependencias del agente no están instaladas** (comentadas en `pyproject.toml`): hoy solo funciona el modo básico |
