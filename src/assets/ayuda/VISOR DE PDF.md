# **Guía del Visor de PDF**

El visor principal de **Extraer PDFs** está diseñado para ofrecerte todas las herramientas que necesitas para leer, editar y procesar tus documentos en una interfaz limpia y organizada. A continuación, te explicamos cada sección y su funcionalidad.

## 1. Pestañas de Navegación
Ubicadas en la parte superior, te permiten tener abiertos múltiples documentos al mismo tiempo.
* Puedes cambiar fácilmente entre la pestaña de **Inicio**, la **Ayuda** o los diferentes **archivos PDF** que tengas abiertos.
* Usa el botón **[ + ]** para abrir una nueva pestaña rápidamente.

## 2. Barra de Herramientas Principal (Navegación y Vista)
Esta es la primera barra de botones, justo debajo de las pestañas. Contiene controles esenciales para leer tu documento:
* **Paginación (`<`, `>`, `[ 1 ] / 14`):** Avanza o retrocede entre las páginas del documento, o escribe un número para saltar directamente a una página específica.
* **Zoom (`-`, `+`, `100%`):** Acerca o aleja el documento para una mejor lectura. También puedes usar el menú desplegable para ajustar el PDF al ancho o alto de tu pantalla.
* **Modos de visualización:** Alterna entre vista de una sola página, desplazamiento continuo o ajuste de página.
* **Deshacer / Rehacer:** Revierte o repite tus últimas anotaciones.
* **Búsqueda rápida (Lupa):** Encuentra rápidamente palabras.
* **Modo Oscuro (Luna):** Cambia la interfaz y el documento a tonos oscuros para reducir la fatiga visual.
* **Botón de OCR:** Realiza OCR sobre la hoja actual del documento.
* **Botón de detección de OCR:** Observa las zonas de detección del OCR en la página.

## 3. Barra de Herramientas de Anotación
La segunda barra contiene todas las utilidades para marcar y editar el contenido del PDF:
* **Selección (Flecha):** Herramienta principal para interactuar con los elementos.
* **Marcador de texto:** Resalta, subraya (`U`) o tacha (`T` con línea) el texto seleccionado.
* **Formas:** Inserta cuadrados, círculos/elipses, líneas y flechas para señalar partes importantes del documento.
* **Dibujo libre (Lápiz):** Realiza trazos a mano alzada.
* **Texto (`T`):** Añade cuadros de texto en cualquier lugar de la página.
* **Paleta de Colores:** Personaliza el color de tus resaltados, formas y textos.
* **Notas (Sticky note):** Agrega notas emergentes con comentarios sin ocupar espacio en el documento.

![alt text](/ayuda_svg/Partes_del_visor.svg)

## 4. Menú Principal (Archivo y Edición de Páginas)
Al hacer clic en el botón de menú superior izquierdo (ícono con líneas/desplegable), encontrarás opciones esenciales para gestionar tu archivo y manipular las páginas:
* **Guardar e Imprimir:** "Guardar cambios", "Guardar PDF como..." para crear una copia, y "Imprimir documento".
* **Rotación y Orientación:** "Rotar 90° a la derecha/izquierda", y "Voltear 180°" (para la página actual o todas). Destaca la opción inteligente **Corregir orientación del escaneo**.
* **Edición de Páginas:** "Insertar página en blanco", "Duplicar página actual" y "Eliminar página actual".
* **Organización:** "Mover página arriba" y "Mover página abajo" para reordenar tu documento.
* **Cerrar:** "Cerrar pestaña" actual.
![alt text](/ayuda_svg/Menu_Principal.svg)


## 5. Panel Lateral de Herramientas Avanzadas
Ubicado en el lado derecho de la pantalla, este panel agrupa las funciones más potentes de procesamiento de documentos. Puedes navegar entre sus diferentes apartados:

* **Índice:** Muestra la estructura y marcadores del documento para una navegación rápida por capítulos o secciones.

![alt text](/ayuda_img/Indice.png)

* **OCR (Reconocimiento Óptico de Caracteres):** Utilízala para extraer texto editable a partir de imágenes o documentos PDF escaneados. El panel muestra el tiempo de procesamiento, la cantidad de segmentos y los resultados aparecen en el recuadro de "Texto extraído".

![alt text](/ayuda_svg/Panel_Lateral_ocr.svg)

### Detalles del Panel de Censura
La herramienta de censura te permite buscar y ocultar de forma permanente información sensible dentro de tu documento. Su interfaz cuenta con las siguientes opciones:

* **Perfiles de Censura:** En la parte superior, puedes seleccionar un perfil existente (por defecto "Sin perfil"). Si configuras una lista de palabras que censuras frecuentemente, puedes usar el botón inferior **Guardar en perfil** para reutilizarla en el futuro.
* **Agregar texto a censurar:** Escribe la palabra, frase o dato que deseas ocultar en el campo de texto y presiona `Enter`. 
* **Buscar en OCR:** Activa este interruptor si tu documento es una imagen o un PDF escaneado. La aplicación utilizará el Reconocimiento Óptico de Caracteres para encontrar y censurar el texto aunque no sea seleccionable.
* **Lista de censuras:** Aquí aparecerán todas las palabras que has agregado. 
    * El panel te mostrará un resumen de las coincidencias encontradas (ej. *7 coincid. en 1 pág.*).
    * Cada término incluye un indicador del número de veces que aparece en el texto.
    * Puedes eliminar cualquier palabra de la lista haciendo clic en la **[ x ]**.
* **Selección de Color:** En la parte inferior, puedes elegir el color del bloque que cubrirá el texto censurado (negro, rojo, azul, verde) o utilizar el selector de color personalizado para elegir otro tono.
* **Aplicar censura al documento:** Una vez que tu lista esté lista y hayas revisado las coincidencias, presiona este botón naranja para aplicar los bloques de color y eliminar la información de forma definitiva del archivo.

![alt text](/ayuda_svg/Panel_de_Censura.svg)

### Detalles del Panel de Buscar
El panel de búsqueda avanzada te permite encontrar palabras o frases específicas en todo el documento de manera organizada y con mayor control que la búsqueda rápida. Sus elementos principales son:

* **Barra de búsqueda:** Escribe el término que deseas localizar en el documento.
* **Coincidir mayúsculas y minúsculas (Ícono 'A'):** Presiona este botón ubicado a la derecha de la barra de búsqueda si necesitas que los resultados coincidan exactamente con las letras mayúsculas y minúsculas que escribiste.
* **Navegación de resultados (`↑` / `↓`):** Utiliza las flechas para desplazarte directamente a la coincidencia anterior o a la siguiente. El indicador central (ej. *1 de 7*) te mostrará en qué resultado te encuentras actualmente.
* **Limpiar búsqueda (`x`):** Borra rápidamente el término ingresado para realizar una nueva búsqueda.
* **Enviar Censura (Ícono de ojo tachado):** Haz clic aquí para enviar a Censurar.
* **Resultados por página:** En la parte inferior se despliega una lista agrupada por páginas (ej. *Pag. 1*). A la derecha de cada elemento se indica el número exacto de coincidencias encontradas en esa página específica. Puedes hacer clic en estos elementos para navegar directamente a dicha sección.

![alt text](/ayuda_svg/Panel_de_Buscar.svg)