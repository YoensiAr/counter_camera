# Actualizar a Camera Counter 3.0.1

Si ya tienes la versión **3.0**, detén el programa y sustituye únicamente la
subcarpeta interna **`camera_counter/`** por la nueva. Copia también la documentación,
`tests/` y `pyproject.toml` si los utilizas. Conserva **`data/`, `config.yaml`,
`models/` y `.venv`**. Arranca de nuevo y recarga el panel con `Ctrl+F5`.
Esta corrección de salidas no añade modelos, dependencias ni migraciones.

Si ya había un desfase en Dentro por salidas omitidas, corrígelo con **Reiniciar
ocupación** cuando el local esté vacío. Esto conserva las identidades y el
historial. Los cruces omitidos anteriormente no se pueden reconstruir solos.

Para versiones anteriores, sigue los pasos completos que aparecen a continuación.

La versión 3 añade reconocimiento corporal y continuidad para entradas/salidas
sin cara visible. Se mantiene una entrada y una salida por identidad y plazo.

1. Detén Camera Counter con `Ctrl+C`. Guarda una copia de tu carpeta actual.
2. Descomprime este ZIP en otra carpeta.
3. Sustituye la subcarpeta **interna `camera_counter/`** de tu instalación por la
   nueva (la que contiene `app.py`, `visitors/` y `web/`). Copia también `scripts/`,
   `tests/`, `docs/`, `README.md`, `ACTUALIZAR.md` y `pyproject.toml`.
4. Copia el **nuevo archivo `models/osnet_x0_25_msmt17.onnx`**,
   `models/osnet_manifest.json`, `models/README.md` y `models/licenses/osnet.txt`.
   Si partes de una versión anterior a 2, copia también los dos ONNX faciales.
5. Conserva tu **`data/` actual**, incluyendo `counter.sqlite3` y `visitors.key`,
   tu **`config.yaml`** y tu **`.venv`** funcional. **No copies el `data/` del ZIP
   encima del de tu equipo**: es la base antigua que enviaste, no tus visitas nuevas.
6. En el bloque `visitors` de tu YAML existente, añade `mode: hybrid` y conserva
   tus otros ajustes. No dupliques el bloque. Por ejemplo:

   ```yaml
   visitors:
     enabled: true
     mode: hybrid
     window: calendar_day
     window_hours: 24
   ```

7. Desde tu carpeta habitual, comprueba los modelos y arranca:

   ```powershell
   .\.venv\Scripts\python.exe scripts/download_face_models.py --check
   .\.venv\Scripts\python.exe scripts/check_body_model.py
   .\.venv\Scripts\python.exe main.py
   ```

8. Recarga el panel con `Ctrl+F5`. Debe mostrar **Rostro + cuerpo + seguimiento**.
   Dibuja la zona alrededor del acceso y coloca la línea sobre el umbral, con
   espacio visible a ambos lados. Comprueba el punto amarillo en ambos sentidos.

Esta actualización utiliza las dependencias de la versión 2.1; añade un ONNX de
891 011 bytes. Si faltan dependencias, ejecuta con tu Python del entorno
`-m pip install -r requirements-windows.txt`. Para una instalación nueva o un
Python dañado, sigue el README. `venv` viene con Python, no se instala con pip.

La migración automática crea `data/counter.sqlite3.before-hybrid-v3.bak` sin
sobrescribir una copia anterior. Conserva historial, claves, referencias y
banderas de entrada/salida. Una referencia antigua que solo tiene cara necesita
ver de nuevo esa cara para asociar sus vistas corporales; si no puede hacerlo,
el cruce puede quedar sin verificar. No borres referencias para actualizar.

## Qué debes comprobar

Entrar → salir de espaldas → volver a entrar debe dejar **Únicos=1, Entradas=1,
Salidas=1 y Dentro=1**, si la identidad se resuelve. Otra salida deja Dentro=0.
El resto del cuarto no debe producir cruces cuando quede fuera de la zona.
Revisa también los casos sin verificar y repite con personas diferentes.

Para una prueba inicial en PC con más detalle puedes ajustar `camera.width: 1280`,
`camera.height: 720` y `detection.image_size: 640` dentro de sus bloques actuales.
Mide FPS en tu equipo. La prueba entregada usa esos tamaños y una línea virtual;
tu línea y el encuadre final necesitan su propia validación.

## Empezar de cero, si lo necesitas

**Reiniciar ocupación** pone Dentro a cero cuando confirmas que el local está
vacío; conserva visitas e identidades del día. **Borrar referencias** olvida las
personas, pero conserva estadísticas y permite volver a contarlas.

Para reiniciar absolutamente todo, detén el programa y **mueve** tu carpeta
`data/` fuera del proyecto como respaldo. Al arrancar se crean base y clave
nuevas. Esto aplica a las rutas predeterminadas; si cambiaste `storage.database`
o `visitors.key_file`, mueve esos archivos y sus archivos SQLite asociados con
el programa detenido. Conserva la base y la clave originales juntas para poder
restaurarlas. No hace falta borrar modelos, configuración ni entorno virtual.
