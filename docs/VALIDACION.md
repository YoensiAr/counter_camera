# Validación de Camera Counter 3.0.1

**226 pruebas aprobadas, sin fallos ni pruebas omitidas**, en Linux x86_64 con
Python 3.12.14. Ruff, sintaxis JavaScript y sintaxis Bash correctos.

## Entorno de ejecución

| Componente | Versión |
|---|---|
| opencv-python | 4.11.0.86 |
| numpy | 2.5.2 |
| ultralytics | 8.4.146 |
| torch | 2.5.1+cpu |
| torchvision | 0.20.1+cpu |
| Flask | 3.1.3 |
| waitress | 3.0.2 |
| cryptography | 48.0.1 |
| pytest | 9.1.1 |

Se usa OpenCV sin ventana para las pruebas. El instalador Windows utiliza
`opencv-python`; la ventana de escritorio necesita comprobarse en Windows.
Se comprobaron tamaño/hash de los tres ONNX y su carga/inferencia con OpenCV CPU.

## Corrección de salidas

Se añadieron ocho casos específicos: regreso rápido en ambas orientaciones y
ambas direcciones, pausa para repetir la misma dirección, desaparición antes de
confirmar y una/diez idas y vueltas con identidad corporal y sin muestras faciales.
Se reprodujeron seis fallos sobre 3.0.0 antes de corregirlos. También se actualizó
una expectativa antigua que aceptaba descartar la salida durante la pausa; ahora
exige registrarla sin retrasos ni emisiones adicionales al permanecer fuera.
Consulta [SALIDAS.md](SALIDAS.md) para los resultados de esta revisión.

## Regresiones cubiertas

| Área | Casos comprobados |
|---|---|
| Conteo | Una entrada y una salida por identidad y plazo; hasta 26 idas/vueltas; ocupación física separada; IDs de cruce no colisionan al reciclar un track |
| Identidad corporal | Alta sin cara, varias vistas, giro gradual, coincidencia tras nuevo ID, continuidad sin reconocimiento facial |
| Rostro y cuerpo | Cara posterior vinculada al cuerpo; caras distintas con cuerpos similares; evidencia facial contradictoria; muestra facial aislada no destruye un recorrido fiable |
| Ambigüedad | Dos candidatos similares, zona gris, una identidad ya visible en otro cuerpo, cuerpos superpuestos, oclusión y salto de posición |
| Pérdida de seguimiento | Cambio de apariencia, muestras caducadas, reutilización de ID, predicciones sin evidencia, reloj que retrocede, pendientes que vencen |
| Persistencia | Reinicio con SQLite/clave, banderas de ambas direcciones, medianoche local, ventana fija de horas, capacidad llena, retención y limpieza sin cámara |
| Protección de datos | Vectores cifrados, galería acotada, modelo incompatible, clave ausente/incorrecta, borrado de cara y cuerpo, CSV sin vectores ni IDs de galería |
| Atomicidad | Concurrencia sobre primera entrada; fallo transaccional sin alta huérfana ni incremento parcial |
| Acceso | Rectángulo excluye movimientos, salir de zona no inventa cruce, puntos centro/pies/superior, coordenadas inválidas y línea fuera de zona rechazadas |
| Ocupación | Advertencia persistente cuando se pierde trayectoria interior; se conserva tras reiniciar y se limpia al reiniciar ocupación |
| Panel/API | Configuración de línea/zona/plazo, totales e informes coincidentes, evidencia en CSV, validación y CSRF |
| Integración existente | ByteTrack y BoT-SORT reales con cámara sintética; captura, colas, grabación, retención, MJPEG, servidor y adaptador IMX500 con metadatos simulados |

Las pruebas lógicas de identidad emplean vectores controlados. Las pruebas del
video ejecutan modelos reales y están separadas en [PRUEBA_VIDEO.md](PRUEBA_VIDEO.md).
No se presenta una prueba de vectores como una medición de reconocimiento humano.

## Pruebas del video

958 fotogramas procesados en modo combinado y sin extracción facial. En ambos:
7 entradas físicas, 6 salidas físicas, **Únicos=1, Entradas=1, Salidas=1**, cero
cruces sin verificar y Dentro=1 al terminar. También se forzaron IDs nuevos,
interrupciones y un reinicio usando datos causales extraídos del mismo clip.
Las interrupciones pueden perder cruces: el aviso de ocupación incierta expone
ese problema y no reconstruye movimientos que la cámara no observó.

Se corrigió además que la preparación de CPU de Ultralytics sobrescribía
`detection.cpu_threads`: se restaura el valor configurado después de preparar
el predictor. OpenCV también limita sus hilos para los modelos de identidad.
No se utiliza el tiempo de este equipo compartido para prometer FPS de la Pi.

## Migración y conservación

En una copia de la base original se conservaron **los 30 eventos y sus columnas
originales, IDs y contadores**; `integrity_check` y `foreign_key_check` correctos.
Las migraciones añaden columnas/tablas y generan copias antes de cada cambio
necesario. El informe está en `evaluation/migracion.json`.

La base dentro del ZIP permanece **idéntica byte por byte** a la entregada
previamente; la migración ocurrirá al iniciar en el equipo del usuario. También
se preserva el YOLO original y la geometría de `config.yaml`. Se explicita
`visitors.mode: hybrid` y se conserva el plazo diario. No se incluyen entorno
virtual, claves del usuario, galerías de prueba ni vectores extraídos del video.

## Comprobaciones que no se completaron aquí

La revisión automática de aprobación rechazó abrir el navegador de pruebas
porque el espacio de trabajo no tenía créditos. No se completó una inspección
visual del panel ni de su comportamiento táctil; las rutas HTTP, plantillas y
sintaxis JavaScript sí tienen comprobaciones locales.

Windows, Raspberry Pi, USB/CSI/IMX500 físicos, la ubicación elevada definitiva,
varias personas reales y ausencias prolongadas requieren validación en el lugar.
Un video de una sola persona no permite afirmar que nunca habrá confusiones.

## Reproducir

```bash
python -m pip install -r requirements-dev.txt
python scripts/download_face_models.py --check
python scripts/check_body_model.py
python -m pytest -q
python -m ruff check camera_counter scripts tests
node --check camera_counter/web/static/app.js
```

Para el video y su línea específica utiliza `scripts/evaluate_video.py`, como se
explica en `PRUEBA_VIDEO.md`. Para probar cruces sintéticos utiliza
`main.py --simulate --diagnose --fast --max-frames 240`; la simulación no reconoce
identidades y su resultado depende de la línea configurada.
