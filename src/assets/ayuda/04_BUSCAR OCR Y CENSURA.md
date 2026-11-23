# 🔎 Buscar, OCR y censura

Encontrar texto, leer el de un documento escaneado y tapar datos de forma permanente. Todo está en el panel lateral del visor.

## Buscar en el documento

Pulsa `Ctrl+F` o la lupa del panel lateral.

![El panel de búsqueda con resultados](/ayuda_img/panel-buscar.png)

* Escribe lo que buscas: los resultados aparecen agrupados por página, con el texto de alrededor resaltado. Pulsa uno para ir a él.
* **Aa** distingue mayúsculas y minúsculas; **ab** busca solo palabras completas.
* Las flechas, o `F3` y `Shift+F3`, van a la coincidencia siguiente y a la anterior.
* Las **tijeras** envían lo que buscas a **Censura**, para taparlo en todo el documento.

> **Consejo:** También puedes seleccionar texto en la página y elegir **Buscar en el documento** en la barra que aparece.

## Índice

Muestra los **marcadores** del PDF (los capítulos y secciones, si el documento los tiene). Pulsa uno para ir a esa parte; la flecha despliega sus apartados.

## OCR: leer el texto de un escaneo

Un PDF escaneado o hecho con fotos es una imagen: no se puede seleccionar ni copiar su texto. El **OCR** (reconocimiento de texto) lo lee.

![El panel de OCR](/ayuda_img/panel-ocr.png)

* Arriba se indica el **tipo** de página: *Digital* (ya tiene texto) o escaneada.
* **Procesar Página Actual:** reconoce el texto de la página que ves.
* **Recorte:** arrastra un rectángulo sobre la página para reconocer solo esa zona.
* **Orientar:** detecta si la página está de lado o al revés y la endereza.
* **Documento:** reconoce todas las páginas, solo las pares o impares, o un intervalo como `1-5, 8`. Al terminar puedes copiar el texto o guardarlo como **.txt**.
* **Mostrar cajas de texto en lienzo:** marca sobre la página cada trozo de texto reconocido.
* El **texto extraído** aparece abajo; el botón de la esquina lo copia.

> **Nota:** El OCR funciona en tu equipo, sin enviar nada a internet. Si el instalador no incluía sus modelos, se descargan una sola vez la primera vez que lo usas.

## Censura: tapar datos para siempre

La censura **borra** el texto y las imágenes que hay debajo y pone un recuadro de color encima. No es una anotación que se pueda quitar: el dato desaparece del archivo.

![El panel de censura](/ayuda_img/panel-censura.png)

1. **Escribe** una palabra, una frase o una expresión regular y pulsa `Intro`: se marcan todas sus apariciones.
    * **Aa** distingue mayúsculas; **W** busca palabras completas.
    * El **rayo** ofrece patrones listos: DNI, correos electrónicos, tarjetas, teléfonos…
2. Activa **Buscar en capas OCR** si el documento está escaneado.
3. **Marcar texto o área en la página:** arrastra sobre un texto o alrededor de una zona (una foto, una firma) para marcarla a mano. `Esc` termina.
4. La **lista de censuras** muestra cada término con sus marcas: pulsa uno para verlas en la página, o quítalo con la papelera.
5. Elige el **color** del recuadro.
6. Pulsa **Aplicar censura al documento** y confirma.

> **Importante:** La censura no se puede deshacer una vez guardada. El documento censurado se guarda como **copia** (Guardar PDF como…), para que conserves el original.

**Perfiles de censura:** si tapas a menudo los mismos datos, guarda la lista como perfil (icono del disquete) y cárgala otro día. El engranaje abre el gestor de perfiles para crearlos, renombrarlos o eliminarlos.

> **Consejo:** También puedes enviar a censura el texto que selecciones en la página o lo que busques en el panel **Buscar**.
