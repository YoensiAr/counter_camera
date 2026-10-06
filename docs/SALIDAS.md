# Revisión de salidas — versión 3.0.1

Se encontró y reprodujo un fallo en la pausa entre eventos. Con
`line.cooldown_seconds: 1`, una entrada confirmada seguida de una salida
confirmada 0.3 segundos después producía únicamente la entrada. El seguimiento
cambiaba al lado exterior, pero la salida no llegaba a SQLite ni se recuperaba
al vencer la pausa. Dentro podía quedar en uno con la persona fuera.

La causa está en `counting/line_counter.py`: el bloqueo temporal se aplicaba a
ambas direcciones por igual. La corrección conserva la última dirección emitida
y aplica la pausa a repeticiones de esa dirección. Un cruce confirmado en sentido
contrario se registra inmediatamente. Se mantiene la exigencia de observaciones
consecutivas en ambos lados, el margen y el segmento finito.

## Resultados de la reproducción

| Caso | Versión 3.0.0 | Versión 3.0.1 |
|---|---|---|
| Entrar y salir con 0.3 s entre confirmaciones | Entrada=1, salida=0, Dentro=1 | Entrada=1, salida=1, Dentro=0 |
| Salir y volver a entrar rápidamente | Se pierde el segundo cruce | Se registran ambos |
| Diez idas/vueltas rápidas, misma identidad corporal | 5 entradas físicas y ninguna salida; Dentro=5 | 10 entradas físicas y 10 salidas; Dentro=0 |
| Contadores únicos de esas diez idas/vueltas | La ausencia de salidas los deja incompletos | Únicos=1, Entradas=1, Salidas=1 |
| Permanecer fuera después de salir | La salida omitida no se recupera | Se cuenta al confirmarse; quedarse fuera no genera otra |
| Rodear el extremo y repetir la misma dirección durante la pausa | Repetición bloqueada | Se conserva ese bloqueo; no aparece un evento al vencer la pausa |
| Solo dos observaciones de salida y desaparición, con tres requeridas | No hay salida confirmada | Se conserva la exigencia; se señala pérdida de trayectoria interior |

Las pruebas de identidad anteriores usan vectores controlados sin muestras
faciales, para aislar la lógica. Se comprobaron ambas orientaciones de la línea.
Los ocho casos añadidos dieron **seis fallos y dos aciertos antes de corregir**;
después pasaron los ocho. La batería completa tiene **226 pruebas aprobadas**.
Una prueba antigua aceptaba perder la salida durante el cooldown: se actualizó
para exigir la salida inmediata y conservar la comprobación de que quedarse
fuera no emite eventos tardíos.

## Video anterior

El video disponible sigue siendo `WIN_20260910_21_03_42_Pro.mp4`. No se ha recibido
una grabación nueva del fallo señalado ahora. Se volvió a ejecutar completo con
YOLO/ByteTrack/OSNet reales y extracción facial desactivada, usando el manifiesto
de la prueba anterior. Los resultados están en `evaluation/salidas_video_3_0_1.json`.

También se reprodujeron sus detecciones previamente extraídas con la línea
conservada en tu `config.yaml`, modificando únicamente el tiempo de reproducción:

| Tiempo de las detecciones | Cruces físicos 3.0.0 | Cruces físicos 3.0.1 |
|---|---:|---:|
| Natural | 7 entradas / 6 salidas | 7 entradas / 6 salidas |
| Dos veces más rápido | 1 entrada / 6 salidas | 7 entradas / 6 salidas |
| Cuatro veces más rápido | 3 entradas / 4 salidas | 7 entradas / 6 salidas |

Las dos aceleraciones son pruebas sintéticas del reloj sobre detecciones reales;
no son nuevas capturas ni mediciones de precisión a mayor velocidad. Sus datos
están en `evaluation/salidas_tiempos_3_0_1.json`.

## Actualización y uso

Si ya usas la versión 3.0, detén el programa y sustituye la subcarpeta interna
`camera_counter/`. Conserva `data/`, `visitors.key`, `config.yaml`, los modelos y
el entorno `.venv`; no hay dependencias ni modelos nuevos en esta corrección.
Reinicia y recarga el panel con `Ctrl+F5`. Consulta también `ACTUALIZAR.md`.

**Salidas** sigue sumando como máximo una vez por identidad dentro del plazo.
**Dentro** utiliza los cruces físicos y debe disminuir en cada salida confirmada,
aunque esa persona ya haya salido antes. Una salida sin identidad suficiente
queda sin verificar; eso no se convierte automáticamente en otra persona.

Si la ocupación ya quedó desajustada por salidas omitidas, usa **Reiniciar
ocupación** cuando el local esté vacío. Conserva las referencias y el historial.
No se reconstruyen retrospectivamente cruces que nunca se guardaron.

Esta revisión corrige el fallo reproducido. No permite asegurar que explique
cualquier salida perdida: hace falta ver el caso concreto si ocurre con pausas
largas, cuerpos tapados o personas que desaparecen antes de confirmar el cruce.
La línea debe quedar con espacio visible a ambos lados para reunir las tres
observaciones; no se inventa una salida cuando simplemente desaparece un cuerpo.
