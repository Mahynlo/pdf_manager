# Modelos de OCR

Modelos de [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) en formato ONNX, licencia Apache-2.0.
Los usa `src/pdf_core/ocr/paddle.py` con onnxruntime; no hace falta PaddlePaddle ni OpenCV.

| Archivo | Modelo | Origen |
|---|---|---|
| `PP-OCRv6_small_det.onnx` | Detección de texto (DB) | [PaddlePaddle/PP-OCRv6_small_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx) |
| `PP-OCRv6_small_rec.onnx` | Reconocimiento (CTC) | [PaddlePaddle/PP-OCRv6_small_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx) |
| `PP-OCRv6_small_rec_dict.txt` | Alfabeto del reconocedor, un carácter por línea | `PostProcess.character_dict` del `inference.yml` del mismo repositorio |
| `PP-LCNet_x1_0_doc_ori.onnx` | Orientación de documento (0/90/180/270°) | [PaddlePaddle/PP-LCNet_x1_0_doc_ori_onnx](https://huggingface.co/PaddlePaddle/PP-LCNet_x1_0_doc_ori_onnx) |

Cada `.onnx` es el `inference.onnx` de su repositorio, renombrado.

## Reconocedor *tiny* (equipos con pocos recursos)

[PP-OCRv6_tiny_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_rec_onnx) ocupa 4,5 MB en lugar de 21 MB
y reconoce unas 5 veces más rápido, a cambio de algo de precisión en escaneos difíciles. Para usarlo:

1. Guardar su `inference.onnx` como `PP-OCRv6_tiny_rec.onnx`.
2. Generar `PP-OCRv6_tiny_rec_dict.txt` con la lista `PostProcess.character_dict` de su `inference.yml`
   (un carácter por línea, UTF-8).
3. Cambiar `REC_MODEL` en `src/pdf_core/ocr/paddle.py` a `"PP-OCRv6_tiny_rec"`.
