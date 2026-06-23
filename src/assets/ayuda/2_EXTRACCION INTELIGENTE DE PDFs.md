# Guía de Extracción Inteligente de PDFs

La herramienta de **Extracción Inteligente de PDFs** está diseñada para automatizar la búsqueda de palabras clave y extraer páginas específicas a través de múltiples documentos de forma simultánea. El proceso se divide en tres pasos principales y un registro visual para llevar el control de tus operaciones.

## Paso 1: Documento de Referencia
En esta sección defines el documento base o plantilla del cual extraerás la información.
* **Abrir PDF Referencia:** Haz clic aquí para seleccionar tu archivo PDF principal.
* **Información del archivo:** Una vez cargado, verás el nombre del archivo ("Referencia") y su formato ("Tipo").
* **# Páginas de referencia:** Escribe los números de las páginas de donde provienen los datos que deseas tomar como referencia. Puedes usar comas para páginas individuales y guiones para rangos (ejemplo: `1,3-5`).

![alt text](/ayuda_svg/Extraccion_Inteligente_Documento_Referencia.svg)

## Paso 2: Patrón de Búsqueda
Aquí configuras los criterios de texto que el sistema utilizará para encontrar la información deseada.
* **Palabras clave / títulos / nombres:** En este recuadro amplio, ingresa los términos, títulos o frases específicas que la herramienta deberá localizar dentro de los documentos objetivo. Puedes ingresar varias palabras separadas por saltos de línea (ej. `VIATICOS`, `GASTOS`, `VIAJE`).
* **Páginas sugeridas en objetivos:** Si sabes en qué páginas de los documentos destino es más probable que se encuentre la información, escríbelas aquí para agilizar la búsqueda (ejemplo: `1,2`).

![alt text](/ayuda_svg/Extraccion_Inteligente_Patron_Busqueda.svg)

## Paso 3: Objetivos y Extracción
Esta sección controla los archivos en los que se buscará la información y dónde se guardarán los resultados finales.
* **Cargar PDFs Objetivo:** Permite seleccionar uno o varios documentos PDF donde se realizará la búsqueda inteligente.
* **Carpeta Destino:** Elige el directorio en tu computadora donde se guardarán los nuevos archivos PDF con las páginas extraídas.
* **Resumen de rutas:** Un recuadro gris te indicará la cantidad de "Archivos objetivo" cargados y la ruta exacta del "Destino" seleccionado.
* **Buscar y Extraer (Botón Azul):** Inicia el proceso automatizado basándose en los parámetros definidos en los pasos anteriores.
* **Abrir Vista Previa:** Te permite revisar los resultados obtenidos antes de dar por finalizado el proceso (este botón se habilitará una vez ejecutada una búsqueda).

![alt text](/ayuda_svg/Extraccion_Inteligente_Objetivos_Extraccion.svg)


## Registro de Operación
Ubicado en la esquina inferior derecha, este panel funciona como una consola de monitoreo en tiempo real.
* Te mostrará el progreso, las acciones realizadas y los resultados detallados de la extracción. Por defecto, mostrará el mensaje "Sin búsqueda ejecutada" hasta que inicies un proceso.
* **Detalle de la consola:**
    * **Resumen general:** En la parte superior indica el estado final, las coincidencias encontradas, los archivos afectados y el nombre del archivo de salida generado.
    * **Información de Referencia:** Muestra los tokens extraídos y las páginas procesadas del documento base.
    * **Análisis por Archivo:** Desglosa el progreso archivo por archivo (ej. `[1/2]`, `[2/2]`).
    * **Advertencias:** Indica si un documento es escaneado y requiere la ejecución de OCR para poder analizarlo.
    * **Estado de página:** Muestra el resultado de la búsqueda en cada página, indicando si hay coincidencia (`✓`) con las palabras clave encontradas o si no coincide (`~`), además del tiempo de procesamiento y el método (Híbrido/OCR).
    * **Archivo Guardado:** Al final, proporciona un enlace directo a la ubicación del nuevo archivo generado con las páginas extraídas.

## Ejemplo de Ejecución
![alt text](/ayuda_svg/Ejemplo_Guia_de_Extraccion_Inteligente.svg)