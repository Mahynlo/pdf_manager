# ✨ Asistente IA

Pregúntale al documento abierto: resúmenes, datos clave, datos sensibles y cualquier duda sobre su contenido.

## Qué hace

Abre el panel **Asistente IA** (la estrella del panel lateral). Responde preguntas sobre el PDF que estás viendo, lo resume, extrae sus datos clave y detecta datos sensibles que puedes enviar a **Censura**.

![El panel del asistente](/ayuda_img/panel-ia.png)

Sin configurar nada funciona en **modo básico**: busca palabras, lee los metadatos y reconoce patrones de datos personales, sin enviar nada fuera de tu equipo. Para respuestas de verdad, configura un proveedor (ver más abajo).

## Conversar

El panel funciona como un chat:

* **Al empezar** propone cuatro acciones: resumen ejecutivo, datos clave, datos sensibles y «¿De qué trata?».
* **Acciones rápidas:** una vez empezada la conversación, los botones **Resumen**, **Datos clave** y **Datos sensibles** quedan sobre el cuadro de texto. **Datos sensibles** pregunta antes qué sensibilidad buscar (baja, media o alta).
* **Escribir:** `Intro` envía la pregunta y `Shift+Intro` añade un salto de línea. Mientras responde se ven tres puntos y los segundos que lleva (los modelos locales pueden tardar).
* **Respuestas:** el botón de copiar aparece al pasar el ratón. Si el proveedor falla, el error ofrece **Reintentar**. Si subes en la conversación, una flecha te lleva al último mensaje.

> **Consejo:** Selecciona un párrafo en la página y elige **Explicar con Agente IA** en la barra que aparece.

## Configurar un proveedor

Pulsa el **engranaje** del panel (**Proveedor de IA**):

* **Google Gemini u OpenAI:** escribe tu clave de API. Se guarda cifrada en este equipo y solo se envía al servidor del proveedor.
* **IA local:** un modelo que corre en tu equipo o en tu red con [Ollama](https://ollama.com) o LM Studio; el documento no sale de ahí.
    * **Dirección del servidor:** Ollama usa `http://localhost:11434/v1` y LM Studio `http://localhost:1234/v1`. Un servidor fuera de tu equipo o de tu red local tiene que usar `https://`.
    * **Clave de API:** opcional; solo si tu servidor la pide.
    * **Contexto del modelo:** el mismo que tenga el servidor (en Ollama, `num_ctx`; en LM Studio, *Context Length*). Si el documento no cabe entero, el modelo recibe los pasajes que más tienen que ver con la pregunta.
* **Modelo:** pulsa **Buscar** para ver los modelos del servidor y elige uno. En la IA local es obligatorio.

> **Importante:** Con Gemini u OpenAI, el texto del documento se envía a sus servidores para responder. Para documentos confidenciales, usa la **IA local** o el modo básico.

> **Nota:** La clave de API solo admite los caracteres visibles del teclado (sin espacios, tildes ni emojis). Si al pegarla da error, revisa que no se haya colado un espacio.
