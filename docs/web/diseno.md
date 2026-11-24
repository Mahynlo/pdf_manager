# Diseño: paleta, medidas e Inicio

Los colores están **todos** en [`app/ui/src/styles/tokens.css`](../../app/ui/src/styles/tokens.css), como
variables CSS, y el tema oscuro las redefine bajo `:root[data-theme="dark"]`. Los componentes usan solo
esos nombres: un color suelto (`#2563EB`) en un `.css` o `.svelte` no cambia con el tema. Excepción: lo
que imita el papel (la página blanca, el modo noche del visor) y los colores que elige el usuario
(resaltados, sellos, censura).

## Paleta

| Grupo | Tokens | Claro | Oscuro | Para qué |
|---|---|---|---|---|
| Neutros | `--bg-header`, `--bg-base`, `--bg-sidebar`, `--bg-card`, `--bg-subtle` | pizarra muy clara (`#EEF2F6` → `#FFFFFF`) | pizarra oscura (`#0B0F15` → `#19202A`) | fondos, de atrás hacia delante |
| Texto | `--text-primary`, `--text-secondary`, `--text-muted` | `#0F172A`, `#475569`, `#64748B` | `#F1F5F9`, `#CBD5E1`, `#94A3B8` | todos con contraste ≥ 4,5 sobre las tarjetas |
| Bordes | `--border-light`, `--border`, `--border-strong` | `#E2E8F0`, `#D5DCE5`, `#94A3B8` | `#263141`, `#334155`, `#52617A` | separadores, campos, bordes al pasar |
| Acento | `--accent` (+ `-hover`, `-pressed`, `-light`), `--bg-selected` | azul `#2563EB` | azul `#3B82F6` | botón principal, selección, foco, enlaces |
| Marca | `--brand`, `--brand-bg` | rojo `#D32F2F` | `#F87171` | el botón «Extraer PDFs» y los PDF de recientes |
| Estados | `--success`, `--warning`, `--danger`, `--gold` (+ `-bg`) | `#15803D`, `#D97706`, `#DC2626`, `#F59E0B` | tonos 400–500 | mensajes, botones de peligro, sellos |
| Herramientas | `--c-blue`, `--c-green`, `--c-amber`, `--c-orange`, `--c-teal`, `--c-violet`, `--c-slate` | tonos 600 | tonos 400 | el icono de cada herramienta |

El color de una herramienta se elige en [`shell/tools.ts`](../../app/ui/src/shell/tools.ts)
(`color: 'var(--c-blue)'`). Llega como `--c` a su tarjeta de Inicio y a su cabecera (`ToolHeader`): el
icono va en ese color sobre un fondo del mismo al 14–15 % (`color-mix`), así que vale para los dos temas
sin más.

Extraer azul, Combinar verde, OCR naranja, Imágenes a PDF verde azulado, Seguridad ámbar, Ayuda violeta y
Configuración gris: los mismos tonos que en las versiones anteriores, ajustados a la paleta.

## Medidas

En [`styles/base.css`](../../app/ui/src/styles/base.css):

* **Letra:** Segoe UI Variable (la de Windows), 13,5 px. Títulos de página 22–28 px en negrita, con
  el espaciado un poco cerrado. Las etiquetas de sección (RECIENTES, HERRAMIENTAS) van en
  11,5 px, mayúsculas, negrita y color `--text-muted`.
* **Radios:** `--radius-sm` 6 px (botones pequeños, etiquetas), `--radius` 8 px (botones, filas),
  `--radius-lg` 12 px (tarjetas, iconos), `--radius-xl` 16 px (zonas grandes como «Abrir un documento»).
* **Sombras:** `--shadow-1` en reposo, `--shadow-2` al pasar por encima y en menús y diálogos.

## Inicio

[`shell/Home.svelte`](../../app/ui/src/shell/Home.svelte) y el bloque «Inicio» de
[`styles/shell.css`](../../app/ui/src/styles/shell.css):

* **Recientes** a la izquierda (`RecentFiles.svelte`), con el tamaño y, en el escritorio, la carpeta
  (`documents.recent` da `size`).
* **Cabecera:** la etiqueta «Todo se procesa en tu equipo», el título y una frase.
* **Abrir un documento:** zona con borde discontinuo y el botón **Abrir archivo** (`Ctrl+O`). Soltar
  archivos funciona en toda la ventana (`dropzone.ts`); la zona se resalta mientras se arrastra
  (`body.is-dropping`). Con pantalla táctil cambia el texto (no hay ni arrastrar ni `Ctrl`).
* **Herramientas:** cuadrícula de tarjetas (`repeat(auto-fill, minmax(240px, 1fr))`) con el icono, el
  título y una frase; una flecha aparece al pasar por encima.

En el móvil las tarjetas pasan a filas (icono a la izquierda), la zona de abrir pone el botón a todo el
ancho y los recientes van debajo. Con poca altura (móvil en horizontal) se quitan la etiqueta, la frase y
los formatos. Ver [responsive.md](responsive.md).

Lo que **no** se pone en Inicio: datos que la app no tiene o que no ayudan a decidir (versiones de
librerías, contadores, filtros para cinco herramientas).
