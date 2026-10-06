# Videos de regresión

`motion_20260910.json` define los 13 tramos, la línea virtual, el hash y las
expectativas del video enviado. No incluye imágenes ni referencias de personas.
Consulta `docs/PRUEBA_VIDEO.md` para los resultados y limitaciones.

Desde la raíz del proyecto:

```bash
python scripts/evaluate_video.py --video /ruta/al/video.mp4 --manifest tests/videos/motion_20260910.json --output pruebas/sin_rostro --no-face --render
```

La herramienta usa SQLite y una clave temporales; no modifica tus estadísticas.
El hash evita probar un video distinto con las expectativas de este manifiesto.
Para un video nuevo crea su propio manifiesto con conteos revisados manualmente.

`python main.py --video /ruta/al/video.mp4` ejecuta la aplicación habitual y sí
registra eventos en su base configurada. Utiliza el evaluador para pruebas aisladas.
