# Modelos locales

Para descargar explícitamente el modelo nano oficial:

```bash
python scripts/download_model.py
```

El modo `auto` usa `models/yolo11n.pt`. En Raspberry Pi, si existe un modelo
NCNN exportado en `models/yolo11n_ncnn_model` y el paquete `ncnn` está instalado,
lo selecciona primero. No se descarga ni exporta un modelo al iniciar el servicio.

El RPK de la IMX500 se configura por separado en `camera.imx500_model`.
La simulación utiliza detecciones sintéticas con un tracker real y no necesita pesos.


## Visitantes únicos (YuNet + SFace)

Este ZIP incluye `face_detection_yunet_2023mar.onnx` (232 589 bytes) y
`face_recognition_sface_2021dec.onnx` (38 696 353 bytes), obtenidos de OpenCV Zoo.
Los originales están enlazados en el README principal. Sus licencias se incluyen
en `models/licenses/`. Funcionan con OpenCV DNN en CPU en Windows y Raspberry Pi.

Verificar los dos archivos sin conexión:

```bash
python scripts/download_face_models.py --check
```

Si faltan, ejecutar el mismo comando sin `--check`. El descargador valida tamaño
y SHA-256 oficiales antes de reemplazar cualquier archivo. No descarga durante
el conteo. El identificador del modelo SFace incluye su hash para impedir mezclar
referencias incompatibles. No copies `data/visitors.key` ni galerías a paquetes
que vayas a distribuir a otras personas.

## Apariencia corporal: OSNet x0.25

La versión 3 incluye `osnet_x0_25_msmt17.onnx` (891 011 bytes), exportado del
checkpoint MSMT17 combineall publicado por el autor en su
[catálogo oficial](https://kaiyangzhou.github.io/deep-person-reid/MODEL_ZOO.html).
La arquitectura, normalización RGB, dimensiones, hashes de código/checkpoint/ONNX
y procedencia están en `osnet_manifest.json`. La licencia MIT del código está en
`licenses/osnet.txt`.

Verificación sin conexión, incluida una inferencia OpenCV CPU:

```bash
python scripts/check_body_model.py
```

Entrada fija `1×3×256×128`, normalización ImageNet; salida de 512 valores con
normalización L2 en la aplicación. Exportación PyTorch 2.5.1, opset ONNX 12, modo
evaluación. El clasificador de entrenamiento no forma parte de la salida.
Los pesos no se ajustaron al video del usuario. La aplicación aprende referencias
temporales de varias vistas, sin alterar este archivo. No requiere Torchreid ni
ONNX Runtime durante el conteo: se ejecuta mediante OpenCV DNN.

No se descarga OSNet al iniciar. Si falta, cópialo del ZIP. Su hash forma parte
del identificador del modelo; cambiarlo con referencias vigentes produce un error
explícito para no comparar espacios incompatibles. No mezcles galerías extraídas
con otros modelos o normalizaciones.
