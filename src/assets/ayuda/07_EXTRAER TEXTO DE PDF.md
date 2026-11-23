# 🔍 Extraer texto de PDF

Busca en muchos PDF a la vez las páginas que mencionan algo y júntalas en un PDF nuevo.

## Para qué sirve

Imagina una carpeta con 200 facturas escaneadas y que solo necesitas las páginas que hablan de «viáticos». **Extraer** las busca en todos los archivos (también en los escaneados, con OCR) y guarda esas páginas en un PDF nuevo, sin abrir los documentos uno a uno.

![La herramienta Extraer con sus partes numeradas](/ayuda_img/extraer.png)

| | Parte | Para qué sirve |
|---|---|---|
| **1** | **Modo** | **Búsqueda inteligente** (por palabras) o **Por rango numérico** (las mismas páginas de cada archivo). |
| **2** | **Documento de referencia** | Opcional: un PDF de ejemplo de lo que buscas. |
| **3** | **Patrón de búsqueda** | Las palabras que buscas y cómo compararlas. |
| **4** | **Documentos objetivo y destino** | Los PDF donde buscar y dónde guardar el resultado. |
| **5** | **Iniciar Búsqueda y Extracción** | Empieza; **Cancelar** la detiene. |
| **6** | **Registro y tabla de coincidencias** | Lo que va pasando y lo que encontró. |

## Paso 1: Documento de referencia (opcional)

Si tienes un ejemplo de la página que buscas (una factura modelo, un certificado), ábrelo con **Abrir PDF Referencia**. Sus palabras ayudan a puntuar más alto las páginas que se le parecen.

* En **Páginas de referencia** indica qué páginas del ejemplo usar, por ejemplo `1,3-5`. Vacío = todas.
* **Quitar** deja de usarlo.

## Paso 2: Patrón de búsqueda

* **Palabras clave:** escribe los términos, una por línea o separados por comas (`viáticos, gastos de viaje`).
* **Preajustes** (el rayo) rellena palabras típicas: facturas, identificación, contratos, balances, certificados.
* **Todas las palabras (AND):** la página debe contenerlas todas. **Cualquier palabra (OR):** basta con una.
* **Ignorar tildes** (á = a), **Distinguir Mayús.** y **Palabras completas** ajustan la comparación.
* **Páginas sugeridas en objetivos:** si sabes que lo que buscas suele estar en ciertas páginas (`1,2`), escríbelas. Vacío = todas.

## Paso 3: Documentos objetivo y destino

* **Cargar PDFs…** o **Añadir Carpeta…** para elegir dónde buscar. **Limpiar** vacía la lista.
* **Destino:** la carpeta donde se guarda el resultado (**Cambiar Carpeta…**, **Abrir Carpeta**).
* **Combinar en un solo PDF** junta todas las páginas encontradas; **Archivos separados por PDF** crea un archivo por cada documento con coincidencias.

Pulsa **Iniciar Búsqueda y Extracción**. Si un PDF tiene contraseña, se te pedirá.

## Resultados

* El **Registro de operación** cuenta, archivo por archivo, qué páginas coinciden, si alguna necesitó OCR y dónde se guardó el resultado.
* La **Tabla de coincidencias** lista cada página encontrada: documento, página, puntuación, términos que coinciden y modo (texto u OCR).
* **Ver PDF Generado** abre el resultado en el visor.

> **Consejo:** Los PDF escaneados tardan más, porque cada página pasa por el OCR. Si sabes en qué páginas suele estar lo que buscas, indícalo en **Páginas sugeridas** para ir más rápido.

## Por rango numérico

Para sacar **las mismas páginas** de muchos archivos sin buscar texto (por ejemplo, la primera página de cada contrato): elige la pestaña **Por rango numérico**, escribe las páginas (`1-3, 5, 8-10`), carga los documentos objetivo y pulsa **Iniciar**.
