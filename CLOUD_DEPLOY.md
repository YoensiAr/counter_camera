# Modo cloud: cámara desde el navegador

Este modo no abre `/dev/video0` ni una cámara física en el servidor. La cámara se abre en Chrome/Edge con `getUserMedia()`, se comprime a JPEG y se envía al backend. El backend conserva YOLO, tracking, conteo, dashboard, SQLite y reportes.

## Probar localmente

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python cloud_server.py
```

Abre `http://localhost:8080`, pulsa **Iniciar cámara de este dispositivo** y acepta el permiso.

## Docker / AWS EC2

```bash
docker build -t counter-camera .
docker run --rm -p 8080:8080 -v counter-data:/app/data counter-camera
```

En producción publica el puerto detrás de HTTPS (ALB, Nginx+Caddy/Let's Encrypt, Cloudflare Tunnel, etc.). Los navegadores bloquean `getUserMedia()` en HTTP remoto; localhost es la excepción.

## Notas

- Ejecuta una sola instancia/worker del backend mientras uses SQLite y una cámara. Múltiples workers crearían runtimes YOLO independientes.
- `config.cloud.yaml` inicia `visitors.enabled: false` porque el repositorio no incluye los pesos ONNX de rostro/cuerpo. El conteo físico, tracking, historial y reportes sí funcionan. Activa visitantes después de instalar esos modelos.
- Para menor latencia, usa una EC2 cercana al sitio de la cámara y, si necesitas más FPS, una instancia con GPU y configura `detection.device`.
- Vercel no es el destino recomendado para este backend persistente de YOLO. El mismo frontend podría vivir allí, pero este paquete está preparado para AWS EC2/VPS/Render-like persistent service.
