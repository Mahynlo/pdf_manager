# :text-cursor-input: Formularios

Rellenar los campos de un PDF, crear tus propios campos y guardar o cargar sus datos.

## La barra de formularios

Pulsa **Formularios** en la barra del visor para abrirla; vuelve a pulsarlo para cerrarla. Es aparte de **Anotar**: abrir una cierra la otra. En el móvil, **Formularios** está en la barra de abajo.

| Parte | Para qué sirve |
|---|---|
| **Rellenar / Editar campos** | El modo. **Rellenar** para escribir en los campos; **Editar campos** para seleccionarlos, moverlos y cambiar sus propiedades. |
| **Crear campo** | Campo de texto, Casilla de verificación, Botón de opción, Lista desplegable y Lista de opciones. |
| **Crear varios seguidos** | La herramienta sigue activa después de crear un campo. |
| **Campo anterior / Campo siguiente** | Pasan de un campo a otro mientras rellenas. |
| **Panel de formularios** | Abre el panel lateral con la lista de campos, sus propiedades y los datos. |

## Rellenar un formulario

1. Abre el PDF y pulsa **Formularios**. Si estaba en **Editar campos**, pulsa **Rellenar**.
2. Haz clic en un campo y escribe, marca la casilla o elige una opción de la lista.
3. Con **Campo siguiente** pasas al siguiente sin buscarlo en la página.
4. Guarda con `Ctrl+S`.

En el **Panel de formularios** ves todos los campos del documento con su valor, la página en la que están y si son **Obligatorio** o **Solo lectura**. Arriba dice cuántos tienen valor («3 de 8 con valor»). Pulsa un campo de la lista para ir a él y dejarlo listo para escribir. Si hay muchos, escribe parte del nombre en el filtro.

Cada cambio se deshace con `Ctrl+Z`.

> **Nota:** Los campos que no tienen borde (habituales en formularios dibujados en la página) se rellenan igual, pero en **Editar campos** puede costar verlos: búscalos en la lista del panel.

## Crear campos

1. En la barra (o en el panel) elige una herramienta de **Crear campo**.
2. Haz clic en la página, o arrastra para darle el tamaño que quieras (salvo casillas y botones de opción).
3. El campo se crea con un nombre como «Texto 1», «Casilla 1» u «Opcion 1», y se pasa a **Editar campos** con él seleccionado y sus propiedades en el panel.

Para poner varios campos del mismo tipo, activa **Crear varios seguidos**: la herramienta sigue activa hasta que pulsas `Esc` o **Editar campos**.

En **Editar campos** un campo se mueve, se cambia de tamaño y se elimina (`Supr`) como una anotación. En la barra que aparece al seleccionarlo, **Propiedades del campo** (o el doble clic) abre sus propiedades en el panel.

## Propiedades del campo

Cada cambio se aplica en el momento. Según el tipo de campo, el panel muestra estas secciones:

**Campo** (todos):

* **Nombre:** identifica el campo y es el nombre que sale al exportar los datos. Va sin tildes (se quitan solas). Cambia al pulsar `Intro` o al salir del cuadro.
* **Obligatorio:** hay que rellenarlo antes de enviar el formulario.
* **Solo lectura:** se ve pero no se puede cambiar al rellenar.
* **No exportar:** no se incluye al exportar los datos.

**Texto** (campos de texto):

* **Longitud máxima:** cuántos caracteres admite. Vacío es **Sin límite**.
* **Multilínea:** permite varias líneas.
* **Contraseña:** lo escrito se ve como puntos.
* **Un carácter por casilla:** reparte el ancho en tantas casillas como la longitud máxima, como en los formularios en papel. Necesita una longitud máxima.

**Opciones** (listas desplegables y listas de opciones):

* Una fila por opción: escribe en ella para cambiarla y pulsa **×** para quitarla. **Añadir opción** pone otra al final.
* **Selección múltiple** (lista de opciones): se pueden elegir varias.
* **Permitir escribir** (lista desplegable): además de elegir, se puede escribir otro valor.

**Botones** (botones de opción):

* **Los botones con el mismo valor se activan a la vez.**
* **Mantener uno activado:** siempre está activo; no se puede quitar.
* La lista de botones del grupo: pulsa uno para ir a él, o **×** para quitarlo.
* **Añadir botón:** otro botón en el mismo grupo, junto al último.
* **Duplicar grupo:** copia los botones debajo, como un grupo nuevo.

**Estilo:** color del borde, relleno, grosor del borde y tamaño de letra, con los mismos botones que las anotaciones.

Al final está **Eliminar campo**.

> **Consejo:** Los campos con el mismo nombre son el mismo campo y comparten el valor. Si le pones a un campo el nombre de otro del mismo tipo, la aplicación te pregunta si quieres **Unir** los dos. Así se agrupan los botones de opción: de un grupo solo puede estar marcado uno.

> **Nota:** Todo se deshace con `Ctrl+Z`, salvo el cambio de nombre y las propiedades de los botones de acción y las firmas que ya traía el PDF.

## Guardar y cargar los datos

En el **Panel de formularios**, en **Datos del formulario**:

* **Exportar datos…:** guarda los valores de los campos en un archivo `.json` (sin los marcados **No exportar**). Sirve de copia o para rellenar otro PDF con los mismos campos.
* **Importar datos…:** rellena los campos con los valores de un `.json` exportado antes. Avisa si algún dato no corresponde a ningún campo.
* **Vaciar formulario:** borra el texto, las casillas y los botones de opción. Las listas conservan la opción elegida. Se deshace con `Ctrl+Z`.

## Guardar el formulario

Los valores y los campos que creaste se guardan **dentro del PDF** con `Ctrl+S` o **Guardar PDF como…**. Son campos estándar: se pueden rellenar en cualquier lector de PDF.

> **Importante:** No se pueden crear botones de acción ni campos de firma digital, y el JavaScript que traiga el formulario no se ejecuta.
