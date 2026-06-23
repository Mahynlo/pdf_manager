# Guía de Gestión de Seguridad de PDFs

La herramienta de **Gestión de Seguridad de PDFs** te permite tomar el control de la privacidad de tus documentos. Desde este panel puedes desbloquear archivos encriptados o proteger tus documentos confidenciales añadiendo contraseñas y restringiendo permisos. Se divide en dos pestañas principales: **Desbloquear** y **Proteger**.

## Pestaña 1: Desbloquear
Utiliza esta sección si tienes un documento protegido y deseas crear una copia completamente libre de contraseñas y restricciones.

*   **Paso 1: Archivo:** Haz clic en **[ Seleccionar PDF Protegido ]** para cargar el documento que deseas desbloquear.
*   **Paso 2: Acciones:** Una vez cargado el archivo, el sistema analizará su estado actual.
    *   **Permisos actuales:** Verás una lista detallada de lo que actualmente se puede hacer con el documento (ej. Impresión permitida, Modificación permitida, Copia de contenido, etc.). Si el archivo ya está libre, te indicará que está "Sin Protección".
    *   **Guardar Sin Contraseña:** Presiona este botón para generar y guardar una nueva versión de tu PDF a la cual se le habrán retirado todas las contraseñas y bloqueos de seguridad.

---


## Pestaña 2: Proteger
Esta sección te permite asegurar tu documento para que solo las personas autorizadas puedan abrirlo, leerlo o editarlo.

![alt text](/ayuda_svg/Seguridad_Desbloquear.svg)

### Paso 1: Archivo y Nivel
*   **Seleccionar PDF a Proteger:** Carga el documento al que deseas aplicar seguridad.
*   **Presets rápidos de permisos:** Utiliza el menú desplegable para aplicar configuraciones comunes de seguridad con un solo clic. Por ejemplo, la opción **"Solo lectura - Ver sin editar ni copiar"** bloqueará automáticamente cualquier intento de modificación.
*   **Permisos personalizados avanzados:** Si necesitas un control más específico, despliega este menú. Podrás marcar o desmarcar casillas individuales para permitir o denegar acciones concretas a los usuarios:
    *   Permitir impresión (calidad estándar o alta calidad).
    *   Permitir modificación de contenido.
    *   Permitir copiar/extraer texto e imágenes.
    *   Permitir agregar comentarios y anotaciones.
    *   Permitir llenar formularios.
    *   Permitir reorganizar y eliminar páginas.

![alt text](/ayuda_svg/Seguridad_Archivo_y_Nivel.svg)

### Paso 2: Contraseñas y Permisos
Aquí defines las claves de acceso para tu documento. El panel incluye un cuadro de ayuda que explica la diferencia entre los dos tipos de contraseñas que puedes aplicar:

*   **Contraseña de Usuario (Para abrir el PDF):** Si estableces esta contraseña, cualquier persona necesitará ingresarla para poder visualizar el contenido del documento.
*   **Contraseña de Propietario (Opcional - Administrador):** Esta es la contraseña "maestra". Quien la posea podrá eludir las restricciones de permisos (como imprimir o copiar) y eliminar la seguridad del documento en el futuro. No es estrictamente necesaria para que un usuario normal lea el archivo si ya tiene la de usuario.
*   **Ocultar/Mostrar contraseñas:** Puedes usar el ícono del "ojo" (`👁️`) a la derecha de los campos de texto para verificar que escribiste la contraseña correctamente.
*   **Cifrar y Guardar PDF:** Una vez configurados los permisos y contraseñas, presiona este botón para aplicar la encriptación y guardar tu nuevo documento protegido.

![alt text](/ayuda_svg/Seguridad_Contrasenas_y_Permisos.svg)
