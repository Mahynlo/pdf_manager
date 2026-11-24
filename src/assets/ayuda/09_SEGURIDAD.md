# :lock: Seguridad

Protege un PDF con contraseña y permisos, o quítale la protección a uno tuyo.

## Proteger un PDF

En la tarjeta **Gestión de Seguridad**, pestaña **Proteger**:

![La pestaña Proteger con sus partes numeradas](/ayuda_img/seguridad-proteger.png)

| | Parte | Para qué sirve |
|---|---|---|
| **1** | **Pestañas** | **Desbloquear** o **Proteger**. |
| **2** | **Seleccionar PDF a Proteger** | El documento al que pones la contraseña. |
| **3** | **Nivel de protección rápido** | Permisos ya preparados. |
| **4** | **Permisos personalizados** | Qué se puede hacer con el PDF, uno a uno. |
| **5** | **Contraseñas** | La de usuario y, opcional, la de propietario. |
| **6** | **Cifrar y Guardar PDF** | Guarda una copia protegida. |

### Niveles rápidos

* **Sin restricciones:** acceso completo.
* **Solo lectura:** ver, sin editar ni copiar.
* **Solo impresión:** imprimir, sin copiar a otro programa.
* **Impresión y lectura:** leer e imprimir, sin editar.
* **Muy restrictivo:** acceso mínimo.

Con **Permisos personalizados avanzados** marcas cada uno: imprimir (normal o en alta calidad), modificar el contenido, copiar texto e imágenes, añadir comentarios, rellenar formularios y reorganizar páginas.

### Las dos contraseñas

* **De usuario (para abrir el PDF):** quien la tenga puede abrirlo y verlo, con los permisos que elegiste.
* **De propietario (opcional):** la «llave maestra». Permite cambiar los permisos o quitar la protección.

El ojo de cada campo muestra lo que escribiste, para comprobarlo.

### Qué contraseñas valen

Para que cualquier lector de PDF pueda abrir el documento, la contraseña nueva solo admite **letras (con acentos y ñ), números, espacios y signos del teclado**. La aplicación avisa en rojo si escribes:

* emojis o símbolos especiales;
* caracteres invisibles (a veces se cuelan al pegar desde otro programa);
* letras de ancho completo o espacios especiales;
* más de 127 bytes (unas 127 letras sin acentos).

> **Importante:** Si olvidas la contraseña de apertura **no hay forma de recuperar el documento**. Guárdala en un lugar seguro.

Pulsa **Cifrar y Guardar PDF** y elige dónde guardar la copia protegida (cifrado AES-256). El original no cambia.

## Desbloquear un PDF

En la pestaña **Desbloquear**:

1. **Seleccionar PDF Protegido.** La aplicación muestra si está protegido, su cifrado y los permisos actuales.
2. Si pide contraseña, escríbela y pulsa **Desbloquear y Abrir**.
3. **Guardar Sin Contraseña** crea una copia sin contraseña ni restricciones.

> **Nota:** Para quitar la protección necesitas conocer la contraseña. La aplicación no rompe contraseñas ajenas.

## Abrir un PDF protegido

No hace falta desbloquearlo para leerlo: ábrelo en el visor y la aplicación te pedirá la contraseña.
