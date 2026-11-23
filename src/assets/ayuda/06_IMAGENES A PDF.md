# 🖼️ Imágenes a PDF

Convierte fotos y escaneos en un PDF, añade imágenes como páginas a un PDF abierto y guarda las páginas como imágenes.

Formatos que se pueden abrir: **PNG, JPG, WebP, BMP, GIF y SVG**.


## Cómo empezar

Hay cuatro formas de abrir imágenes:

* **Tarjeta de Inicio:** pulsa **Imágenes a PDF** y elige una o varias imágenes.
* **Menú principal:** **Imágenes a PDF…**
* **Abrir** (`Ctrl+O`): el diálogo acepta PDF e imágenes. Si eliges varias imágenes, se juntan en un solo documento.
* **Arrastrar:** suelta las imágenes sobre la ventana desde el Explorador.

Las imágenes que no se pueden leer se avisan y se omiten; las demás siguen adelante.


## El diálogo «Imágenes a PDF»

Cada imagen será una página.

![El diálogo Imágenes a PDF con sus partes numeradas](/ayuda_img/imagenes-dialogo.png)

| | Parte | Para qué sirve |
|---|---|---|
| **1** | **Ajustes de todas las páginas** | Tamaño de hoja, orientación, margen y ajuste. |
| **2** | **Las páginas** | Todas tal como quedarán. Arrastra para cambiar el orden; **Añadir imágenes…** agrega más al final. |
| **3** | **Vista grande** | La página elegida, con su hoja y su margen. |
| **4** | **Ajustes de esta página** | Su orientación propia. |
| **5** | **Girar, subir, bajar y quitar** | La página elegida. |

### Ajustes de todas las páginas

* **Tamaño de hoja:** A4, Carta, Oficio (21,6 × 34 cm), Legal, A5, A3 o **Igual que la imagen** (la hoja toma la forma de la imagen, con el lado mayor de un A4).
* **Orientación de todas:**
    * **Automática:** cada página sale vertical u horizontal según la forma de su imagen. Una foto alargada queda en vertical y una captura de pantalla en horizontal, sin hacer nada.
    * **Vertical** u **Horizontal:** todas iguales.
* **Margen:** sin margen, pequeño (5 mm), normal (10 mm) o amplio (20 mm).
* **Ajuste:**
    * **Encajar entera:** se ve toda la imagen; puede quedar espacio en blanco a los lados.
    * **Rellenar (recorta):** la imagen cubre toda la hoja y se recorta lo que sobra.

Con **Igual que la imagen** no hacen falta la orientación ni el ajuste: la hoja ya tiene la forma de la imagen.

La aplicación recuerda los últimos ajustes que usaste.

### Vista previa de las páginas

* La cuadrícula muestra **cada página como quedará en el PDF**, con su hoja, margen y orientación.
* Pulsa una página para verla en grande. Debajo se indica, por ejemplo, «Página 2 de 5 · A4 horizontal · 29,7 × 21 cm». En la vista grande el margen se marca con una línea punteada.
* Pasa de una página a otra con **‹ ›** o con las flechas del teclado.
* **Arrastra** las páginas de la cuadrícula para cambiar el orden.

### Ajustes de cada página

Debajo de la vista grande:

* **Orientación de esta página:**
    * **Como todas:** sigue el ajuste general.
    * **Vertical** u **Horizontal:** solo para esta página. Úsalo cuando la orientación automática no es la que quieres. La página lleva un **lápiz azul** en la cuadrícula y no cambia aunque cambies la orientación de todas.
* **Girar** 90° a la derecha (para fotos tomadas de lado).
* **Subir** y **Bajar** para ordenar.
* **Quitar** la página (también con `Supr`).
* **Añadir imágenes…** (arriba de la cuadrícula) agrega más imágenes al final.

Pulsa **Crear PDF**.

> **Consejo:** Las fotos JPG se guardan tal cual, sin recomprimir: no pierden calidad ni ocupan más. Las fotos del móvil salen derechas (se respeta su orientación). Las imágenes PNG conservan la transparencia.


## El documento nuevo

El PDF se abre en una pestaña del visor como **documento nuevo, sin guardar** (lleva un punto ● en la pestaña). Puedes usar todo el visor: anotar, poner sellos y firmas, reconocer el texto con **OCR** (útil para fotos de documentos: el texto se podrá buscar y copiar), girar o reordenar páginas.

Para guardarlo pulsa `Ctrl+S`: como aún no tiene archivo, se abre **Guardar como**. Desde entonces es un PDF normal y aparece en Archivos recientes.


## Desde los botones «Páginas» y «Exportar» del visor

En la barra superior del visor (en el móvil, dentro del menú **⋮**):

* **Páginas → Insertar páginas desde imágenes…:** elige imágenes y se añaden como páginas detrás de la página actual, con el mismo diálogo. Se puede deshacer (`Ctrl+Z`).
* **Páginas → Ajustar imagen de la página…:** rehace la página actual con otro tamaño de hoja, orientación, margen, ajuste o giro. Se puede deshacer.
    * Solo está disponible en las páginas creadas desde imágenes **mientras el documento sigue abierto**. Al cerrarlo y volver a abrirlo, esas páginas pasan a ser páginas normales.
    * Las anotaciones de esa página se quitan al ajustarla (con `Ctrl+Z` vuelven).
* **Exportar → Exportar páginas como imágenes (PNG, JPG)…:** guarda cada página como una imagen, con sus anotaciones, en la carpeta que elijas.
    * **Formato:** PNG (sin pérdida) o JPG (ocupa menos).
    * **Resolución:** 96 ppp (pantalla), 150 ppp (recomendada) o 300 ppp (impresión).
    * **Páginas:** todas, la actual o un intervalo como `1-3, 5`.
    * Los archivos se llaman como el documento con el número de página: `informe_p1.png`, `informe_p2.png`… (con un cero delante, `informe_p01.png`, si el documento tiene 10 páginas o más, para que se ordenen bien).
    * En la versión de navegador, si el navegador no deja elegir carpeta, las imágenes se descargan.

> **Nota:** No confundir con **Extraer todas las imágenes del documento…**, que saca las imágenes originales que lleva dentro el PDF (fotos, logotipos), sin las anotaciones ni el resto de la página.
