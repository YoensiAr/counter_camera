# Prueba del video y alcance del aprendizaje

Video: `WIN_20260910_21_03_42_Pro.mp4`, 1280×720, 958 fotogramas, aproximadamente
32.05 s de imagen. Se procesaron todos los fotogramas con YOLO11n/ByteTrack,
YuNet/SFace y OSNet reales, sin sustituir los modelos por respuestas preparadas.

La línea virtual de la prueba está en x=0.35, desde y=0.98 a y=0.28, con entrada
hacia la derecha, margen 15 px y confirmación de tres observaciones. YOLO utiliza
`image_size: 640` y el punto central del cuerpo. Esa línea no sustituye tu línea
actual. Las idas y vueltas dentro del cuarto son cruces de prueba; no se describen
como trece visitas reales a una tienda.

## Resultado completo

| Ejecución | Cruces entrada/salida | Únicos | Entradas | Salidas | Sin verificar | Dentro final |
|---|---:|---:|---:|---:|---:|---:|
| Versión facial anterior, mismo video/línea | 7 / 6 | 1 | 1 | 1 | 2 | 1 |
| Versión 3, rostro + cuerpo + recorrido | 7 / 6 | 1 | 1 | 1 | 0 | 1 |
| Versión 3, extracción facial desactivada todo el video | 7 / 6 | 1 | 1 | 1 | 0 | 1 |

El modo sin rostro hizo **cero inferencias faciales** y obtuvo 107 muestras
corporales; el modo combinado obtuvo 43 muestras faciales y 107 corporales.
La primera entrada corporal se verifica aproximadamente a los 2.44 s; la primera
salida a los 5.32 s. Los otros once cruces quedan como repetidos y no suman otra
entrada/salida. No hubo errores de los modelos en esas ejecuciones.

Los JSON en `docs/evaluation/` contienen los cruces, decisiones y resultados por
tramo. No incluyen vectores ni galerías. El video anotado de entrega corresponde
a una ejecución del modo sin rostro, repetida después de limitar los hilos con
los mismos conteos y decisiones: la imagen original conserva las caras visibles, pero el
reconocimiento facial está desactivado. El rótulo indica esa condición.

## Tomas y movimientos revisados

Estos tramos cubren el video completo; las fronteras están redondeadas para su
lectura. Cada fotograma se procesa, pero se extraen referencias a intervalos de
0.3 s para no tratar imágenes casi idénticas como evidencia independiente.

| Intervalo | Movimiento observado |
|---|---|
| 0.00–2.44 s | Aproximación y giro de frente a perfil |
| 2.44–5.32 s | Primer recorrido lateral y vuelta |
| 5.32–7.23 s | Retorno lateral hacia el interior |
| 7.23–10.34 s | Cuerpo frontal y desplazamiento inverso |
| 10.34–12.55 s | Giro y cuerpo parcialmente fuera de cuadro |
| 12.55–16.49 s | Recorrido frontal, perfil y comienzo de giro de espalda |
| 16.49–18.40 s | Recorrido de espaldas |
| 18.40–21.28 s | Espalda, perfil y vuelta |
| 21.28–23.02 s | Desplazamiento lateral rápido |
| 23.02–26.09 s | Cuerpo frontal y retorno |
| 26.09–27.57 s | Cambio de sentido |
| 27.57–30.44 s | Perfil y giro hacia la cámara |
| 30.44–32.08 s | Aproximación a cámara y cuerpo recortado |

## Interrupciones y reapariciones forzadas

Estas pruebas adicionales reutilizan detecciones y vectores extraídos del video,
con muestras causales de no más de 0.1 s de antigüedad. Cambian artificialmente
la disponibilidad de datos; **no son nuevas grabaciones ni mediciones de precisión
sobre personas diferentes**. Las pruebas con modelos reales de arriba ejercitan
también los filtros de calidad del recorte; estas repeticiones se centran en la
lógica de identidad/persistencia.

| Escenario | Resultado |
|---|---|
| Usar cara solo durante los primeros 3 s | 1 único, 1 entrada, 1 salida; ningún cruce sin verificar |
| No usar caras | 1 único, 1 entrada, 1 salida; ningún cruce sin verificar |
| Forzar otro ID de seguimiento cada 150 fotogramas | No duplica; 1 entrada y 1 salida. Dos cruces finales sin verificar; ocupación marcada como incierta |
| Quitar observaciones en frames 300–344 y 600–719 | No duplica identidad. Pierde cruces: 6 entradas físicas/4 salidas, Dentro=2; aviso de ocupación incierta |
| Reiniciar servicio/SQLite en frame 510, conservando la clave | 1 único, 1 entrada, 1 salida; referencias persistentes recuperadas |

El video mantiene un único ID de ByteTrack durante toda la ejecución natural.
Por eso su resultado positivo demuestra continuidad y aprendizaje de distintas
vistas; por sí solo **no demuestra reidentificación tras horas fuera de cámara**.
Las reasociaciones corporales y los reinicios se comprueban además en las pruebas
forzadas y en la batería automatizada.

## Qué significa «entrenar» en esta versión

Se incorporó un modelo corporal OSNet x0.25 preentrenado publicado por su
[autor](https://kaiyangzhou.github.io/deep-person-reid/MODEL_ZOO.html).
Los pesos no se reajustaron con este video. La aplicación **aprende referencias
cifradas de hasta seis vistas de cada identidad temporal** durante recorridos
fiables. Esas referencias caducan al terminar el día o el plazo configurado.
No se guarda la persona del video como identidad permanente de todas las
instalaciones.

Este clip contiene una persona y no aporta ejemplos negativos de otras personas.
Entrenar o bajar umbrales hasta que todas sus poses coincidan podría empeorar la
distinción entre clientes. Para ajustar un modelo para el local se necesitan
secuencias etiquetadas de distintas personas, entradas/salidas de espaldas, ropa
parecida, oclusiones, iluminación real y capturas con la cámara elevada definitiva.
Se deben separar recorridos completos entre ajuste y validación; dividir frames
vecinos entre ambos produciría una medición engañosa.

## Repetir esta prueba sin tocar estadísticas reales

Con el video original en una ruta de tu equipo:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_video.py --video "C:\ruta\WIN_20260910_21_03_42_Pro.mp4" --manifest tests/videos/motion_20260910.json --output pruebas/hibrido
.\.venv\Scripts\python.exe scripts/evaluate_video.py --video "C:\ruta\WIN_20260910_21_03_42_Pro.mp4" --manifest tests/videos/motion_20260910.json --output pruebas/sin_rostro --no-face --render
```

Se crean base y clave dentro de una carpeta temporal que se elimina al terminar.
`--output` contiene el informe y, con `--render`, un MP4 sin audio. El programa
comprueba el hash del video y termina con código distinto de cero si no cumple
los conteos esperados o si hay errores de reconocimiento. `--face-until 3` limita
la extracción facial a los primeros tres segundos. No ejecutes `main.py --video`
contra tu base habitual si solo quieres una prueba aislada.

Para otro video, crea su propio manifiesto con hash, dimensiones, línea, tramos y
conteo observado manualmente; no reutilices las expectativas de este clip. Sin
manifiesto se usa la línea predeterminada y se informa lo obtenido, pero no se
puede afirmar que el conteo sea correcto por carecer de una referencia manual.

## Límites que quedan por medir

La cámara del clip no está en la posición alta definitiva. No hay una prueba real
con varias personas, uniformes, cambio de ropa, largas ausencias ni horas de
operación continua. La ropa parecida puede causar falsos emparejamientos y cambiar
la apariencia puede causar omisiones o duplicados. Las reglas de ambigüedad reducen
riesgos, pero no dan una garantía absoluta. Los resultados de este clip no son una
tasa de precisión para una tienda ni una cifra de rendimiento de Raspberry Pi.
