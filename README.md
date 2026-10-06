# Camera Counter

Contador local de visitas para Windows y Raspberry Pi: **YOLO → ByteTrack o
BoT-SORT → cruce confirmado → identidad temporal → SQLite → panel Flask**.
Cuenta visitantes únicos durante un plazo configurable con **OSNet (cuerpo),
YuNet + SFace (rostro) y continuidad observada del recorrido**.
La verificación funciona localmente en CPU, tanto en Windows como en Raspberry Pi.
El programa procesa una cámara por instancia.

Incluye cámaras USB, CSI/Picamera2, Sony IMX500, videos, RTSP y una simulación
que alimenta **los trackers reales** con detecciones sintéticas. La simulación
no necesita pesos ni cámara física y no simula identidades faciales.


## Corrección 3.0.1: salidas inmediatas

Se corrige una pérdida de salidas/entradas cuando la persona confirma un regreso
antes de vencer `cooldown_seconds`. La pausa ahora protege repeticiones de la
misma dirección: un cruce confirmado en sentido contrario se registra de inmediato.
Se conservan la confirmación por fotogramas, la franja y el segmento finito.

Las repeticiones físicas actualizan Dentro; cada identidad sigue sumando como
máximo una entrada y una salida por plazo. Consulta [SALIDAS.md](docs/SALIDAS.md)
para la reproducción, las pruebas y cómo actualizar sin borrar datos.

## Versión 3.0: cuerpo, rostro y recorrido sin repetir el conteo

Con la verificación de visitantes activada, cada identidad reconocida suma **como máximo una entrada
y una salida dentro del plazo configurado**. La versión 2 solo deduplicaba
“Visitantes únicos”; esta versión aplica la regla también a **Entradas** y
**Salidas** en las tarjetas, el texto sobre el video, el historial y el CSV de
totales. Funciona aunque ByteTrack le asigne otro ID o se reinicie el programa,
siempre que se conserven la base de datos, la clave y los mismos modelos.

| Ejemplo, dentro del plazo | Visitantes únicos | Entradas | Salidas | Dentro |
|---|---:|---:|---:|---:|
| Una persona entra y se verifica su identidad | 1 | 1 | 0 | 1 |
| Esa persona sale y se verifica | 1 | 1 | 1 | 0 |
| Vuelve a entrar y se reconoce | 1 | 1 | 1 | 1 |
| Vuelve a salir y se reconoce | 1 | 1 | 1 | 0 |
| Entra otra persona y se verifica | 2 | 2 | 1 | 1 |

Cada reingreso se registra aparte. Los cruces físicos repetidos siguen actualizando
**Dentro**, porque una persona que regresa vuelve a ocupar el local. No se calcula
la ocupación restando las dos cifras deduplicadas. Si se ve primero una salida
(por ejemplo, alguien ya estaba dentro al iniciar), puede sumar una salida
verificada sin inventar una entrada.

**La cara ya no tiene que verse en cada cruce.** La aplicación conserva hasta
seis vistas corporales por identidad y aprende giros mientras el seguimiento es
continuo y fiable. Una salida de espaldas puede verificarse usando ese recorrido
o una coincidencia corporal clara. También admite una primera entrada sin rostro
si reúne evidencia corporal suficiente.

**La identidad por apariencia sigue siendo una estimación.** Ropa similar, cambios
de ropa, oclusiones, cuerpos recortados y cambios de cámara pueden causar dudas o
errores. Una comparación ambigua queda pendiente y después **sin verificar**;
conserva el cruce físico, pero no aumenta Entradas, Salidas ni Únicos. El tracker
no convierte por sí solo dos apariciones separadas en la misma persona.

Se añade una **zona de acceso dibujable**, elección de punto de cruce (centro,
pies o parte superior de la caja), comprobación de discontinuidades y aviso de
ocupación incierta. El punto superior es geométrico: no es un detector de cabeza.

El ZIP conserva tu línea, la base original y el modelo YOLO adjunto. Incluye el
nuevo modelo OSNet, los dos modelos faciales y sus licencias. Usa `hybrid` y
`calendar_day` por defecto. El entorno `.venv` se conserva o crea en tu equipo.
Consulta [PRUEBA_VIDEO.md](docs/PRUEBA_VIDEO.md): el video completo se usa como
regresión de movimientos, sin afirmar que entrenar con una sola persona permita
reconocer de forma infalible a cualquier visitante.

### Actualizar una instalación existente

Sigue **[ACTUALIZAR.md](ACTUALIZAR.md)**: además de sustituir la subcarpeta interna
`camera_counter/`, debes copiar **`models/osnet_x0_25_msmt17.onnx`**, su manifiesto
y los scripts actualizados. Conserva tu `config.yaml`, `.venv` y `data/` actuales,
incluidos `counter.sqlite3` y `visitors.key`. No sobrescribas los datos de tu equipo
con la base antigua incluida en el ZIP.

La migración crea una copia `counter.sqlite3.before-hybrid-v3.bak`, conserva la
memoria vigente y añade vistas corporales cifradas. Las identidades antiguas con
solo rostro necesitan una nueva observación facial fiable para vincular el cuerpo;
una coincidencia corporal sin referencia previa puede quedar sin verificar hasta
entonces o hasta caducar. No se reconstruyen rostros/cuerpos de eventos antiguos.

Después reinicia el programa y recarga el panel con `Ctrl+F5`.
`venv` forma parte de Python: **no se instala con `pip install venv`**.
Si Python falla con `No module named encodings`, repara primero Python y crea un
entorno nuevo; no copies un `.venv` entre equipos o versiones.

## Empezar en Windows

Instala Python 3.11 de 64 bits, descomprime el proyecto y abre PowerShell dentro
de la carpeta que contiene `main.py`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
if (-not (Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml }
.\.venv\Scripts\python.exe scripts/download_face_models.py
.\.venv\Scripts\python.exe main.py --simulate
```

Abre **http://127.0.0.1:8080**. La simulación completa genera dos entradas y una
salida cada ciclo; una de las trayectorias incluye una oclusión breve. Los IDs
los asigna ByteTrack, no la cámara simulada. Detén el programa con `Ctrl+C`.

Si `config.yaml` ya existe, conserva tu archivo y omite `Copy-Item`.
También puedes ejecutar `scripts/install_windows.ps1`; realiza esos pasos sin
sobrescribir la configuración existente. No necesitas activar el entorno virtual.

### Usar una cámara USB

Descarga el modelo **una sola vez**, explícitamente:

```powershell
.\.venv\Scripts\python.exe scripts/download_model.py
.\.venv\Scripts\python.exe scripts/camera_test.py --scan-usb
.\.venv\Scripts\python.exe main.py --camera usb --source 0
```

Selecciona uno de los índices detectados. Cierra otras aplicaciones que estén
usando la cámara y concede acceso a las aplicaciones de escritorio en
Configuración de Windows → Privacidad y seguridad → Cámara.

Para abrir además una ventana OpenCV:

```powershell
.\.venv\Scripts\python.exe main.py --camera usb --source 0 --gui
```

`Q` o `Esc` cierran la ventana y el servicio. Para CUDA, instala una combinación
de PyTorch/Torchvision adecuada al equipo con el
[selector oficial de PyTorch](https://docs.pytorch.org/get-started/locally/).
Con `device: auto`, un modelo `.pt` usa CUDA si está disponible y CPU en caso contrario.
YuNet, SFace y OSNet permanecen en CPU.

## Instalar en Raspberry Pi

La imagen oficial consultada el **10 de septiembre de 2026** es Raspberry Pi OS
de 64 bits basado en **Debian 13 Trixie**. Bookworm permanece como versión Legacy.
Usa Raspberry Pi Imager para instalar la edición Lite si no necesitas escritorio.
[Descargas oficiales](https://www.raspberrypi.com/software/operating-systems/).

Conecta la cámara CSI con la Pi apagada. Enciende y comprueba el sistema:

```bash
cat /etc/os-release
getconf LONG_BIT
uname -m
sudo apt update
sudo apt full-upgrade
```

Se requiere `64` y `aarch64`. Dentro de la carpeta del proyecto:

```bash
bash scripts/install_raspberrypi.sh
sudo reboot
```

El instalador instala `python3-picamera2`, `python3-opencv`, `python3-numpy`,
`python3-venv`, `rpicam-apps` e `imx500-all`. Crea `.venv` con
`--system-site-packages` y fija NumPy a la versión de `apt` para conservar la ABI
de las extensiones de cámara. `numpy-system-constraints.txt` refleja tu sistema.

Tras reiniciar, vuelve a la carpeta del proyecto:

```bash
rpicam-hello --list-cameras
rpicam-hello --timeout 5000 --nopreview
.venv/bin/python -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
.venv/bin/python main.py --simulate --headless
```

La instalación de firmware mediante `imx500-all` y el reinicio proceden de la
[guía oficial de la AI Camera](https://www.raspberrypi.com/documentation/accessories/ai-camera.html).
La primera carga del firmware puede tardar varios minutos. La disponibilidad de
paquetes y el rendimiento final deben comprobarse en la Pi concreta.
La creación del entorno con paquetes del sistema sigue el
[manual oficial de Picamera2](https://pip.raspberrypi.com/documents/RP-008156-DS).

### IMX500: comenzar con inferencia en la Pi

La IMX500 es una cámara CSI para Raspberry Pi. Windows puede ejecutar el proyecto
con USB, RTSP y archivos; no controla directamente ese conector CSI.

```bash
.venv/bin/python scripts/download_model.py
.venv/bin/python main.py --camera imx500 --source 0 --headless
```

Sin `camera.imx500_model`, Picamera2 captura la imagen y YOLO trabaja en el
equipo. El panel indica el fallback. Esto permite comprobar la captura antes de
preparar la inferencia dentro del sensor. `--camera csi` sirve para otras cámaras
compatibles con Picamera2.

### Ejecutar YOLO dentro del sensor IMX500

Necesitas un **YOLO de detección exportado y empaquetado como `.rpk`**. Un `.pt`
no se ejecuta directamente en el sensor. Este adaptador espera NMS integrado y
tensores separados: `boxes[N,4]`, `scores[N]`, `classes[N]` y, opcionalmente,
`n_valid`. No interpreta cabezas YOLO crudas, segmentación ni pose.

1. Exporta en un entorno separado de desarrollo, siguiendo la
   [guía oficial de exportación IMX500](https://docs.ultralytics.com/integrations/sony-imx500/).
   El ejemplo utiliza YOLO11n, compatible con esa ruta. La exportación puede
   instalar dependencias adicionales y descargar datos de calibración.

   ```bash
   yolo export model=models/yolo11n.pt format=imx data=coco8.yaml imgsz=640
   ```

2. Copia el resultado a la Pi si exportaste en otra máquina. Empaqueta **en la Pi**:

   ```bash
   sudo apt install imx500-tools
   imx500-package -i models/yolo11n_imx_model/packerOut.zip -o models/imx500
   ```

3. Configura `config.yaml`:

   ```yaml
   camera:
     type: imx500
     source: 0
     imx500_model: models/imx500/network.rpk
     imx500_person_class: 0
     imx500_bbox_order: xy
     imx500_boxes_normalized: false
     imx500_preserve_aspect_ratio: true
     allow_cpu_fallback: true
   ```

4. Ejecuta `.venv/bin/python main.py --config config.yaml --headless`.

El empaquetado usa el comando publicado por
[Raspberry Pi](https://www.raspberrypi.com/documentation/accessories/ai-camera.html#model-deployment).
El contrato por defecto corresponde al exportador Ultralytics **8.4.146**: cajas
XYXY en píxeles del tensor. Para un RPK que entregue coordenadas normalizadas,
pon `imx500_boxes_normalized: true`; para YXYX, `imx500_bbox_order: yx`.

El adaptador convierte al formato YXYX normalizado requerido por
`convert_inference_coords`, y esa API aplica los recortes y escalas de la imagen.
Obtiene imagen y metadatos de la **misma solicitud** y libera la solicitud incluso
si hay errores. Acepta tanto una tupla como un objeto Rectangle de Picamera2.

Si faltan tensores, no repite detecciones antiguas. Si vence el timeout o el
contrato resulta incompatible, cambia a YOLO en el equipo y lo indica. Sin
fallback, informa el error. Los modelos de ejemplo MobileNet distribuidos por
Raspberry Pi no se presentan como modelos YOLO.

**Pendiente de validación física:** exportar el RPK concreto, cargar firmware,
confirmar el orden/escala de sus tensores, comprobar los recortes y medir FPS y
precisión en el acceso real. La lógica del adaptador tiene pruebas con metadatos
y tensores simulados; eso no sustituye esas comprobaciones.

## Modos de ejecución

Con el entorno activado, o sustituyendo `python` por su ruta dentro de `.venv`:

| Objetivo | Comando |
|---|---|
| Selección automática y panel | `python main.py --config config.yaml` |
| USB | `python main.py --camera usb --source 0` |
| Escritorio | `python main.py --camera usb --gui` |
| Servidor sin monitor | `python main.py --camera imx500 --headless` |
| Sin panel ni ventana | `python main.py --headless --no-web` |
| Video de prueba | `python main.py --video tests/videos/entrance.mp4` |
| Simulación | `python main.py --simulate` |
| Prueba determinista | `python main.py --simulate --diagnose --fast --max-frames 240` |
| Diagnóstico de cámara/modelo | `python main.py --camera usb --diagnose` |
| Panel accesible por LAN | `python main.py --host 0.0.0.0 --port 8080 --headless` |

`--headless` desactiva la ventana; `--no-web` desactiva el panel. Un archivo termina
al llegar a su último fotograma. La simulación sin límite se repite hasta `Ctrl+C`.
`--diagnose` utiliza SQLite en memoria, no graba y no cambia tus contadores.
Dispone de 45 segundos para obtener una muestra; durante la primera carga lenta de
firmware, comprueba primero la cámara con las herramientas del fabricante.

No se incluyen imágenes ni galerías de personas en el ZIP. Los modelos locales
y sus licencias están incluidos; las secuencias sintéticas están en `tests/` y `MockCamera`.

### RTSP y configuración por entorno

Para evitar credenciales en YAML, usa `CAMERA_COUNTER_SOURCE`. Ejemplo en PowerShell:

```powershell
$env:CAMERA_COUNTER_SOURCE = "rtsp://IP_DE_LA_CAMARA:554/RUTA_DEL_STREAM"
.\.venv\Scripts\python.exe main.py --camera rtsp --headless
```

Sustituye la URL por la proporcionada por tu cámara. Otras variables admitidas:
`CAMERA_COUNTER_HOST`, `CAMERA_COUNTER_PORT`, `CAMERA_COUNTER_WEB_TOKEN`.
El programa no lee `.env` automáticamente. SQLite guarda `camera.name`, nunca
la URL de conexión. Los mensajes propios ocultan URLs RTSP.

## Panel desde teléfono u otra computadora

Ejecuta con `--host 0.0.0.0`. En el otro dispositivo de la misma red, abre
`http://IP_DEL_EQUIPO:8080`. Consulta la IP con `ipconfig` en Windows o `hostname -I`
en la Pi. Permite el puerto en el firewall del perfil privado si está bloqueado.

Para proteger el panel, define `CAMERA_COUNTER_WEB_TOKEN` antes de iniciar.
El navegador pedirá usuario **admin** y esa clave. En `systemd`, puedes definirla
en un archivo local `service.env`, con permisos `600`. Está excluido de Git.
El panel usa HTTP y está diseñado para una LAN de confianza; esa clave no cifra el enlace.

El panel ofrece:

- Video MJPEG, estado de cámara/modelo, FPS, latencia, memoria y frames descartados.
- Visitantes únicos, reingresos, cruces sin verificar, entradas y salidas sin repeticiones y ocupación.
- Plazo por día local o por horas; referencias vigentes y borrado manual con confirmación.
- Línea dibujada con dos pulsaciones o introducida como coordenadas normalizadas.
- Dirección, tolerancia, confirmaciones y cooldown editables sin reiniciar.
- Historial por hora/día y CSV de totales sin repeticiones; descarga separada de todos los cruces.
- Grabación opcional y reinicio de ocupación con confirmación.

Cambiar la línea guarda únicamente ese bloque en YAML y vuelve a establecer las
posiciones iniciales: mover una línea sobre una persona no genera una entrada.
Los cambios de grabación del panel son de la ejecución actual; el valor de YAML
determina el próximo inicio. No hay CDN, fuentes remotas ni servicios externos en la interfaz.

## Regla exacta de conteo

La clase COCO `0=person` es la única que llega al tracker. ByteTrack es el valor
predeterminado. BoT-SORT es configurable y funciona con ReID y compensación de
movimiento global desactivados para una cámara fija.

Cada ID temporal tiene historial acotado, primera/última observación, posición
anterior, lado estable, lado candidato, dirección, confianza y eventos emitidos.
La máquina de estados usa `UNKNOWN`, `OUTSIDE`, `CROSSING`, `INSIDE`,
`COUNTED_ENTRY` y `COUNTED_EXIT`.

1. Confirma `confirmation_frames` observaciones en un lado de la franja.
2. Verifica que el recorrido intersecta el **segmento finito**, no su prolongación.
3. Espera salir del margen y confirma varias observaciones consecutivas en el otro lado.
4. Emite el cruce confirmado según `entry_to`. El cooldown solo bloquea repetir la última dirección emitida; un retorno en sentido contrario se registra inmediatamente. Cada cruce tiene un número de secuencia.

Las predicciones del flujo óptico intermedio se dibujan con `~`, pero no cuentan.
Las confirmaciones son observaciones reales de inferencia: con stride 3 no equivalen
a tres frames de captura. Una observación ausente rompe la confirmación consecutiva.

**Los cruces físicos se registran también al salir y volver con el mismo ID.**
Permanecer en un lado o moverse dentro de la franja no crea otro evento. La
verificación de identidad decide si esa persona ya sumó la dirección correspondiente
durante el plazo; el ID de ByteTrack no es su identidad persistente.

ByteTrack conserva tracks perdidos durante `max_lost_seconds`. Al perder un ID,
se elimina su memoria de seguimiento; las referencias de visitantes siguen en
SQLite hasta su propia caducidad. Una nueva cámara/sesión confirma posiciones de
nuevo. Los cruces que ocurran con el programa apagado no se pueden recuperar.

Los puntos de la línea usan `[x,y]` entre `0` y `1`, con origen arriba a la izquierda:

| Línea orientada | Lado positivo | Lado negativo |
|---|---|---|
| Izquierda → derecha | Abajo | Arriba |
| Arriba → abajo | Izquierda | Derecha |

Los dos semiplanos separados por la franja son las zonas de entrada/salida. Para
invertirlas, cambia `entry_to`. También se admite un segmento diagonal. Monta la
cámara fija, encuadra ambos lados y deja espacio para confirmar las trayectorias.

## SQLite, reinicios y ocupación

Cada evento registra fecha UTC, día/hora local, tipo, track temporal, nombre de
cámara, confianza media del historial reciente, dirección y UUID de sesión.
La combinación `(sesión, track_id, tipo, número_de_cruce)` es única. El evento y los totales se
guardan en una sola transacción con WAL y acceso sincronizado entre hilos.

- Reiniciar el proceso conserva eventos, totales y referencias de rostro y cuerpo vigentes; crea una sesión de seguimiento nueva.
- Reconectar una cámara inicia otra sesión y establece posiciones de nuevo.
- **Reiniciar ocupación** desde el panel establece un nuevo periodo para el balance
  físico y registra el reinicio. Conserva las entradas/salidas contadas hoy,
  visitantes únicos y referencias. Hazlo cuando el local esté vacío.
- La ocupación es `max(0, entradas_acumuladas_del_periodo - salidas_acumuladas_del_periodo)`.
  Un saldo negativo genera un log y un aviso visible; no se inventan entradas para compensarlo.
- Entradas y salidas del panel suman las primeras verificaciones de cada dirección
  registradas hoy, según la ventana vigente. No se reinician con el botón de
  ocupación. La ocupación acumulada tampoco se borra a medianoche.
- El historial y el CSV incluyen los eventos anteriores al reinicio, dentro de la retención.
- La retención elimina eventos antiguos; conserva por separado el balance acumulado.
  Se ejecuta al iniciar y cada hora. SQLite reutiliza espacio libre.

La secuencia de cruces y las posiciones visibles se conservan al reiniciar
contadores. Las referencias de identidad también sobreviven: el reinicio de los
contadores no permite contar otra vez al mismo visitante dentro de su plazo.
La ocupación es una estimación que parte de un establecimiento vacío al comenzar
el primer periodo; no se calcula restando salidas a visitantes únicos.

### API e informes

| Campo o informe | Contenido |
|---|---|
| `/api/status`: `counted_entries_today`, `counted_exits_today` | Totales que muestran panel y video. Con reconocimiento activo, una vez por persona y dirección dentro del plazo. |
| `/api/status`: `entries_today`, `exits_today`, `entries`, `exits` | Cruces físicos internos, conservados por compatibilidad; los diarios respetan el reinicio físico. No usar estos campos para mostrar el conteo sin repeticiones. |
| `/api/history`: `counted_entries`, `counted_exits` | Totales sin repeticiones por hora o día, anteriores o posteriores a un reinicio. `entries` y `exits` conservan los cruces físicos. |
| `/reports/summary.csv` | CSV del panel: visitantes únicos, reingresos, sin verificar, entradas y salidas deduplicadas. |
| `/reports/events.csv` | Detalle de todos los cruces, con `suma_al_contador` (0/1) y `evidencia` (face, body o continuity). Filtrar por 1 o sumar esa columna para reproducir los totales. |

En el detalle, `new` significa primera verificación **de esa dirección** y
`returning` significa repetición de esa dirección. `first_entry` y `first_exit`
indican el motivo. Una primera salida no aumenta “Visitantes únicos”, que cuenta
primeras entradas. En modo desactivado o simulación cada cruce suma y se marca
`disabled`; el panel lo indica explícitamente.

## Configurar visitantes únicos

En el panel, usa **¿Cuándo volver a contar a una persona?** y pulsa **Guardar plazo**.
También puedes editar el YAML con el programa detenido:

```yaml
storage:
  timezone: America/Santo_Domingo
visitors:
  enabled: true
  mode: hybrid
  window: calendar_day
  window_hours: 24
```

| Ajuste | Comportamiento |
|---|---|
| `calendar_day` (predeterminado) | Una entrada y una salida hasta la próxima medianoche en `storage.timezone`. Entrar a las 23:59 y volver a las 00:01 puede contar en ambos días. |
| `hours`, `window_hours: 24` | Una entrada y una salida durante 24 horas exactas desde el primer cruce verificado, entrada o salida. Volver no prolonga el plazo. |
| `window_hours` | Admite de 1 a 168 horas. Solo se utiliza en modo `hours`. |
| `enabled: false` | Entradas y salidas cuentan cada cruce, sin deduplicación de identidad. Las referencias existentes conservan su caducidad. |

Al cambiar el plazo desde el panel, se recalcula la caducidad de las referencias
que todavía existen **desde su primer cruce verificado**, no desde la hora del cambio.
No se recuperan referencias ya eliminadas. En modo horas, una entrada o salida ya
contada ayer no vuelve a sumar hoy antes del vencimiento; las primeras direcciones
verificadas hoy sí suman. Para personas distintas en cada fecha, usa `calendar_day`.
Reiniciar ocupación no altera estos totales diarios.

### Cómo se verifica una entrada o salida

1. YOLO y el tracker aportan cuerpos observados. Se rechazan predicciones, cajas
   pequeñas, borrosas y cuerpos superpuestos para aprender identidad.
2. YuNet/SFace reúnen al menos dos muestras faciales coherentes si hay cara útil.
   OSNet reúne al menos tres muestras corporales coherentes de 512 valores.
3. Al cruzar la línea se registra el movimiento físico. La identidad puede esperar
   hasta ocho segundos para reunir evidencia del mismo recorrido antes/después
   del cruce. Un salto espacial, superposición o cambio brusco de apariencia
   invalida la continuidad; no se hereda la identidad por reutilizar un número ID.
4. Una cara clara tiene prioridad. Si no está visible, se utiliza continuidad
   reciente o una coincidencia corporal clara y separada de otras candidatas.
   Dos cuerpos visibles no pueden ocupar a la vez la misma referencia.
5. Solo se crea una identidad nueva con evidencia suficiente y sin coincidencias
   dudosas. Las primeras vistas se conservan; se añaden vistas diversas durante
   un recorrido fiable. Una reasociación solo por cuerpo no modifica libremente
   la galería, para limitar la contaminación progresiva.
6. La referencia, la bandera de dirección y la decisión se guardan de forma
   transaccional. Repetir el cruce o reiniciar no vuelve a sumar dentro del plazo.

Los umbrales iniciales son coseno facial `0.50` (coincidir) / `0.35` (distinto),
corporal `0.85` / `0.55`, y separación entre candidatas `0.08`. Son decisiones de
esta aplicación, **no una exactitud medida ni una calibración universal**. Bajar
umbrales hasta que todas las vistas de una persona coincidan puede fusionar a
otras personas. Los casos grises se conservan sin verificar.

Las muestras de trabajo caducan a los tres segundos; se extrae como máximo una
por track cada 0.3 s, con reparto entre tracks. Se almacenan hasta seis vistas
corporales por referencia y 10 000 identidades vigentes por defecto. No se expulsa
una identidad vigente para admitir otra y luego contarla otra vez. Estos ajustes
están en `config.example.yaml`; cambios manuales requieren reinicio.

El aprendizaje es **de referencias temporales de distintas vistas**, no un
reentrenamiento automático de YOLO/OSNet. Los pesos incluidos son preentrenados.
La procedencia y el hash de OSNet están en `models/osnet_manifest.json`.

### Referencias, caducidad y archivos

Se guardan referencias faciales y corporales **cifradas con Fernet** en SQLite. La clave se crea
localmente en `data/visitors.key`. No se almacenan recortes, fotografías, nombres
ni otros atributos de personas; tampoco se envían rostros a servicios externos.
Una referencia facial sigue siendo un dato biométrico, aunque no contenga un nombre.
La API, CSV y logs no exponen vectores ni identificadores de la galería.

La comparación excluye referencias vencidas inmediatamente. La limpieza elimina
filas vencidas al iniciar, cada 30 segundos de ejecución (también sin imágenes) y
al cerrar. Al borrarlas se quita su vínculo del evento; se mantienen los conteos
agregados y la clasificación histórica, con la retención de eventos configurada.
Si el programa está apagado, la limpieza se ejecuta en el siguiente inicio.
Se vacía la memoria de muestras/pendientes al reconectar, cambiar configuración,
borrar referencias y cerrar. No se prolonga la retención por observar a alguien.

El botón **Borrar referencias** elimina la galería y su memoria de trabajo;
conserva los totales históricos. Después de borrarla, alguien puede contarse otra
vez como nuevo. No lo uses como reinicio diario: la caducidad ya se encarga de eso.

Mantén la base y su clave juntas para reinicios/restauraciones. Una clave ausente o
incorrecta, o cambiar el modelo con referencias vigentes, produce un error explícito;
no se reemplaza silenciosamente la galería. La clave está excluida de Git. El cifrado
no protege frente a alguien que tenga acceso tanto a la base como a la clave:
protege la carpeta y el acceso al equipo. Los backups y las grabaciones opcionales
tienen su propio ciclo de conservación; borrar referencias no borra videos/backups.
SQLite usa `secure_delete` y checkpoints de WAL, sin prometer borrado forense de
copias, snapshots o soportes físicos.

### Montaje elevado sobre la entrada

1. Fija la cámara y encuadra ambos lados de la puerta con luz uniforme. Una vista
   alta y oblicua que conserve torso/cuerpo facilita reunir apariencia corporal;
   una toma totalmente cenital que solo vea coronillas requiere validación aparte.
2. Pulsa **Delimitar acceso**, marca dos esquinas opuestas alrededor del paso y
   guarda. Debe haber espacio de observación a ambos lados de la línea: una zona
   demasiado estrecha impide confirmar cruces. La zona filtra cruces; el detector
   sigue viendo la imagen completa para mantener continuidad.
3. Dibuja la línea en el umbral. Elige centro, pies o parte superior según el punto
   visible y revisa el punto amarillo al pasar en ambos sentidos. La línea debe
   atravesar la zona; la flecha señala la entrada. No coloques la línea en medio
   del cuarto si esos paseos no son entradas reales.
4. En un PC comienza probando `camera.width: 1280`, `camera.height: 720` y
   `detection.image_size: 640`. Son los tamaños usados en la prueba adjunta, no
   una garantía de FPS en Pi. El perfil general mantiene valores más ligeros.
5. Comprueba entrar, salir de espaldas, regresar, girar, desaparecer, reiniciar y
   volver dentro del plazo. Repite con varias personas, ropa parecida, mochila,
   cambios de luz y cruces simultáneos. Revisa también **Sin verificar** y el CSV.

Si se pierden imágenes o seguimiento, la ocupación puede desviarse. El panel
muestra incertidumbre detectada al perder una trayectoria conocida dentro, al
reconectar o al cambiar la zona con conteos activos. No detecta necesariamente
todos los cruces perdidos. Confirma que el local está vacío antes de reiniciarla.

En IMX500, YOLO puede ejecutarse en el sensor; **YuNet/SFace y OSNet trabajan en
la CPU de la Pi** sobre la imagen capturada. Hay que medir carga y precisión en
el hardware instalado. El video enviado no reproduce esa posición elevada.

## Rendimiento y grabación

`model: auto` elige el YOLO11n local. En Pi prefiere el NCNN nano local si existe y
`ncnn` está instalado. `device` también permite elegir explícitamente un dispositivo
admitido por el backend de Ultralytics. Cada formato/acelerador necesita sus dependencias.
No se promete un FPS concreto sin medir la Pi y la cámara.

La captura y el procesamiento usan productor/consumidor con cola limitada. En directo
se descartan frames antiguos; en archivos y simulación se conserva el orden completo.
`inference_stride` reduce inferencias y usa flujo óptico solo para la visualización
intermedia. Subirlo demasiado puede perder cruces rápidos. Las detecciones de baja
confianza se conservan para la segunda asociación de ByteTrack.

El panel solo codifica fotogramas JPEG mientras hay un espectador conectado; sin
espectadores evita ese trabajo adicional y conserva intactos la captura, la inferencia
y el conteo.

La latencia indicada va desde que se recibe el frame hasta el resultado de conteo;
no incluye el transporte al navegador. FPS describe frames procesados por segundo,
no la especificación del sensor. También se mide FPS de inferencia y RSS del proceso.

La grabación está **desactivada por defecto**. Activarla crea MP4 anotados con prefijo
`counter_`, segmentos, retención y cuota. Los huecos cortos repiten el frame anterior
para mantener la escala temporal; los largos abren otro segmento. No se graba audio.
La limpieza solo considera archivos `counter_*.mp4` de la carpeta configurada.

## Inicio automático con systemd

Instala las dependencias y configura la cámara y el modelo primero. Ejecuta como
tu usuario habitual, desde el proyecto:

```bash
.venv/bin/python scripts/install_service.py
sudo install -m 644 camera-counter.generated.service /etc/systemd/system/camera-counter.service
sudo systemctl daemon-reload
sudo systemctl enable --now camera-counter
sudo systemctl status camera-counter
journalctl -u camera-counter -f
```

El generador usa el usuario y la ruta reales, sin asumir `/home/pi`. La unidad
necesita los grupos `video` y `render` de Raspberry Pi OS. Para cambiar configuración:

```bash
sudo systemctl restart camera-counter
```

Para detener el servicio y desactivar el arranque automático:

```bash
sudo systemctl disable --now camera-counter
```

El servicio reinicia si termina, espera cinco segundos entre intentos y recibe
SIGTERM para cerrar cámara, grabación, servidor y SQLite. La captura reintenta si
se pierde la señal. Un controlador nativo bloqueado tiene un límite de espera al
cierre; `systemd` aplica `TimeoutStopSec` como último recurso.

Los logs propios rotan en `logs/` (cinco copias de aproximadamente 2 MB), además
del journal de `systemd`. Ejecuta una sola instancia por cámara/base de datos; no
arranques varios workers WSGI que intenten controlar la misma cámara.

## Pruebas y validación

```bash
python -m pip install -r requirements-dev.txt
python scripts/download_face_models.py --check
python scripts/check_body_model.py
python -m pytest -q
python -m ruff check .
python main.py --simulate --diagnose --fast --max-frames 240
```

Las pruebas incluyen los diez casos solicitados y casos adicionales de segmento
finito, dirección vertical, cambio de línea, cooldown, retención, CSV, CSRF,
grabación reproducible, colas, MJPEG y cierre del servidor. **No se sustituyen
ByteTrack ni BoT-SORT por trackers falsos** en las pruebas de integración.

Consulta [VALIDACION.md](docs/VALIDACION.md) para los resultados y el alcance exacto.
La instalación Windows/Pi, la ventana de escritorio, la revisión visual del panel
en teléfonos y el funcionamiento físico de USB/CSI/IMX500 requieren verificación
en esos equipos; las pruebas ejecutadas aquí no certifican ese hardware.

## Problemas frecuentes

| Síntoma | Acción |
|---|---|
| `py -3.11` no existe | Instala Python 3.11 de 64 bits o usa un Python compatible que ya tengas. Consulta `py --list`. |
| PowerShell bloquea la activación | Usa directamente `.venv\Scripts\python.exe`, como en la guía; no necesitas activar el entorno. |
| Falta el modelo | Ejecuta `scripts/download_model.py` o configura una ruta local válida. |
| CUDA/DLL/Torchvision incompatibles | Dentro del venv, reinstala Torch y Torchvision juntos con el selector oficial; usa CPU para aislar el problema. |
| OpenCV no abre ventanas | Instala `opencv-python`; las variantes `headless` no incluyen interfaz gráfica. En un venv de prueba, conserva una sola variante de OpenCV. |
| Cámara ocupada o USB sin imagen | Cierra aplicaciones de cámara, revisa permisos e índices con `camera_test.py --scan-usb`. |
| `picamera2` o `libcamera` ausente | Instálalos mediante `apt`; crea el venv con `--system-site-packages`. No intentes instalar libcamera con pip. |
| Error de ABI NumPy en Pi | Recrea el venv con el instalador, manteniendo la versión NumPy de apt mediante el archivo de restricciones. |
| El sensor no entrega tensores | Verifica firmware/RPK/contrato y observa el estado de fallback en el panel. |
| `--diagnose` termina antes de la primera carga de firmware | Verifica y precarga la cámara con las herramientas oficiales; vuelve a ejecutar el diagnóstico. |
| Muchas entradas sin verificar | Revisa cuerpo visible, rostro disponible, tamaño, luz y superposición; consulta `motivo_verificacion` en el CSV. No reduzcas umbrales sin medir falsos emparejamientos. |
| Faltan modelos faciales | Ejecuta `python scripts/download_face_models.py`; verifica con `--check`. |
| Falta o no coincide la clave de referencias | Restaura la clave original junto con su base. No generes una nueva encima de la existente. |
| Un reingreso aumenta únicos | Confirma que estaba dentro del mismo plazo y se guardó su referencia en la primera entrada. Revisa cambios de modelo, borrados, luz, pose y umbrales; no hay garantía de exactitud absoluta. |
| El teléfono no conecta | Revisa misma LAN, IP, `host: 0.0.0.0` y el firewall privado. |
| El video no carga con varias pestañas | Cierra espectadores o aumenta `web.max_stream_clients` dentro de la capacidad de la Pi. |

## Organización del código

`main.py` delega en `camera_counter/cli.py`. `cameras/` contiene adaptadores y
captura; `detection/`, YOLO y trackers; `counting/`, geometría y estados;
`database/`, SQLite; `visitors/`, reconocimiento y galería temporal; `web/`,
rutas/plantillas/estilos; `utils/`, logs y video.
`scripts/` contiene instalación y diagnóstico; `systemd/`, la plantilla del
servicio; `tests/`, secuencias y pruebas.

Las rutas de datos/modelos son relativas al YAML. Las rutas absolutas que aparecen
en herramientas del sistema o en la unidad generada corresponden al sistema operativo.
El paquete no incluye claves faciales de usuarios ni una galería de personas.
Incluye OSNet, YuNet/SFace y el modelo YOLO del archivo adjunto, sin guardar imágenes por
defecto. Ultralytics se inicia con `YOLO_OFFLINE=true`, `YOLO_AUTOINSTALL=false` y
`sync=false`. Las descargas/exportaciones son pasos explícitos de instalación.

## Referencias

- [OSNet y modelos oficiales](https://kaiyangzhou.github.io/deep-person-reid/MODEL_ZOO.html).
- [Seguimiento de Ultralytics](https://docs.ultralytics.com/modes/track/).
- [API ByteTrack](https://docs.ultralytics.com/reference/trackers/byte_tracker/).
- [API BoT-SORT](https://docs.ultralytics.com/reference/trackers/bot_sort/).
- [Exportación YOLO a IMX500](https://docs.ultralytics.com/integrations/sony-imx500/).
- [AI Camera de Raspberry Pi](https://www.raspberrypi.com/documentation/accessories/ai-camera.html).
- [Código oficial Picamera2/IMX500](https://github.com/raspberrypi/picamera2/blob/main/picamera2/devices/imx500/imx500.py).
- [YuNet oficial](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).
- [SFace oficial](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface).
- [API FaceRecognizerSF](https://docs.opencv.org/4.x/da/d09/classcv_1_1FaceRecognizerSF.html).
- [Cifrado Fernet](https://cryptography.io/en/latest/fernet/).
- [Licencia y condiciones de Ultralytics](https://www.ultralytics.com/license).

El proyecto no descarga modelos ni dependencias durante la ejecución normal. La
licencia de Ultralytics y de los pesos es independiente de tus datos y configuración;
consulta sus condiciones si vas a distribuir el sistema.

## Cámara desde navegador / despliegue cloud

Para ejecutar YOLO y el conteo en un servidor sin conectar físicamente la webcam al servidor, usa el nuevo modo `browser`:

```bash
python cloud_server.py
```

Abre `http://localhost:8080` para una prueba local. En AWS/VPS usa HTTPS, abre el panel desde el equipo que tiene la cámara y pulsa **Iniciar cámara de este dispositivo**. El navegador captura la webcam y envía los frames al servidor; YOLO, tracking, conteo, SQLite e informes siguen ejecutándose en el backend.

Consulta `CLOUD_DEPLOY.md` para Docker/AWS y las consideraciones de producción.
