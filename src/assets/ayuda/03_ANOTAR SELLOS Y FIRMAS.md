# :pen-line: Anotar, sellos y firmas

Resaltar, escribir, dibujar, poner sellos y firmar sobre el PDF.

## La barra de anotaciones

Pulsa **Anotar** en la barra del visor para abrirla; vuelve a pulsarlo para cerrarla. Elige una herramienta y úsala sobre la página: se queda activa hasta que eliges otra. Al cerrar la barra vuelves a la selección de texto.

![La barra de anotaciones con sus grupos numerados](/ayuda_img/barra-anotaciones.png)

| | Grupo | Herramientas |
|---|---|---|
| **1** | **Marcar texto** | Resaltar, Subrayar, Tachar, Subrayado ondulado, **Indicar texto omitido** (marca dónde falta texto y escribes lo que falta) y **Reemplazar texto** (tacha lo que sobra y escribes el texto nuevo). Arrastra sobre el texto. |
| **2** | **Formas** | Rectángulo, círculo o elipse, línea, flecha, **polilínea** y **polígono** (clic en cada vértice; doble clic para terminar). |
| **3** | **Trazos libres** | Pluma, **marcador** (trazo translúcido, como un rotulador) y dibujo fino. |
| **4** | **Insertar** | **Texto** (`T`): clic donde quieras escribir. Con el clic derecho sobre el botón eliges **Texto con flecha** (llamada) o **Nota adhesiva**. **Imagen**: elige un archivo y haz clic donde colocarla. |
| **5** | **Estilo** | El de la herramienta elegida: colores rápidos y, según la herramienta, **color**, **grosor**, **relleno** y **tamaño de letra**. Cada herramienta recuerda el suyo, también al cerrar la app. |

> **Consejo:** Para resaltar rápido no hace falta abrir la barra: selecciona el texto con la herramienta de selección y elige **Resaltar** en la barra que aparece.

Si la ventana es estrecha, cada grupo se junta en un botón: muestra la última herramienta que usaste y su flecha abre las demás.

## Editar una anotación

Elige el **Puntero** (en la barra del visor) y haz clic sobre la anotación:

* **Arrástrala** para moverla, o usa las flechas del teclado.
* Tira de sus **esquinas** para cambiar el tamaño.
* En la barra que aparece cambias su **color**, el **grosor** del trazo, el **relleno** de las formas y el **tamaño de letra** (solo lo que tiene esa anotación), y tienes **Editar texto**, **Traer al frente**, **Enviar al fondo** y **Eliminar** (`Supr`).
* En las **figuras** y los **trazos** tienes además **Duplicar** (`Ctrl+D`) y **Crear sello**, que guarda lo seleccionado en **Propios** del panel de sellos para ponerlo en cualquier PDF.

Todo se puede deshacer con `Ctrl+Z`.

## Color, grosor y relleno

Los botones de estilo abren un panel pequeño, en la barra de anotaciones y en la de una anotación seleccionada:

* **Color:** pulsa uno de la paleta y se aplica. En **Personalizado** eliges cualquiera: con el cuadro y la barra de colores, escribiendo su código (`#1565C0`) o con el cuentagotas, que toma un color de la pantalla. Se aplica al pulsar **Aplicar**, y se guarda en **Recientes**.
* **Grosor:** de 0,5 a 100 puntos. Mueve el deslizador, pulsa un valor rápido o escribe el número exacto y pulsa `Intro`. La vista previa muestra cómo queda. El panel sigue abierto para afinar; ciérralo con `Esc` o pulsando fuera.
* **Relleno** (rectángulo, elipse, polígono y texto): un color o **Sin relleno**.
* **Tamaño de letra** (texto): de 6 a 96 puntos, igual que el grosor.

## Texto en la página

* El cuadro de **texto libre** crece mientras escribes para que se vea todo.
* Admite letras con acentos, la ñ, números y los signos habituales (€, comillas, guiones…).

> **Nota:** Los emojis se pueden escribir, pero se guardan como texto: según el lector de PDF con que se abra, pueden verse o no.

## Sellos

Abre el panel **Sellos y firmas** (el icono del sello del panel lateral). Elige un sello y haz clic en la página para colocarlo; `Esc` cancela.

![El panel de sellos](/ayuda_img/panel-sellos.png)

* **Estándar:** Aprobado, Borrador, Confidencial, Final, Completado, Nulo, las flechas de Testigo, Inicial y Firma, la marca ✔ y la ✘…
* **De texto:** tus leyendas, como «PAGADO» o «REVISADO». Con **Sello de texto…** las creas: escribe el texto, elige el tamaño y el color y pulsa **Guardar Nuevo**. También desde **⋮ → Gestionar Leyendas y Sellos**.
* **Propios:**
    * **Desde imagen…:** un logotipo o una firma escaneada (PNG, JPG o SVG).
    * **Desde lo seleccionado:** convierte en sello las anotaciones que hayas seleccionado con el Puntero (deben estar en la misma página). Útil para repetir un conjunto de texto y formas.

Un sello colocado se mueve, se cambia de tamaño y se elimina como cualquier anotación. Los sellos de texto quedan como **texto libre**: se pueden editar.

> **Nota:** Las leyendas solo admiten letras, números y signos habituales: los emojis y símbolos como ✓ no se pueden usar porque la letra del PDF no los tiene.

## Firmas

En el mismo panel, pestaña **Firmas** → **Nueva firma…**:

1. Elige cómo hacerla: **Dibujar** (con el ratón, el dedo o un lápiz), **Escribir** tu nombre con una letra manuscrita, o subir una **Imagen**.
2. Si quieres, añade tus **iniciales**.
3. Elige el color de la tinta.
4. Marca **Guardar en este equipo para reutilizarla** si la vas a usar otras veces; si no, se borra al cerrar la aplicación.
5. Pulsa **Crear firma**, después pulsa la firma (o las iniciales) y haz clic en la página.

> **Importante:** Es una firma **visual** (un trazo o una imagen), sin certificado digital. No sustituye a una firma electrónica con validez legal.

## Guardar las anotaciones

Las anotaciones, sellos y firmas se guardan **dentro del PDF** al pulsar `Ctrl+S` o **Guardar PDF como…**. Son anotaciones estándar: se ven en cualquier lector de PDF, y en muchos se pueden seguir editando.
