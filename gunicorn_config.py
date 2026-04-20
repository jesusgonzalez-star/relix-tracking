import os
import multiprocessing

# Configuración del servidor Gunicorn para producción (Linux)
# En Windows dev se usa app.run() directamente; este archivo solo aplica en Linux.

# Binding — 127.0.0.1 para uso detrás de Apache/Nginx reverse proxy.
# Para exponer directo (sin proxy), cambie GUNICORN_BIND=0.0.0.0:<port> en entorno.
bind = os.getenv('GUNICORN_BIND', f"127.0.0.1:{os.getenv('PORT', 5000)}")

# Workers: (cores * 2) + 1 es la fórmula estándar, pero en Docker/VM ajustar manualmente
# Para máquinas con 2-4 cores: WORKERS=3-5. Para 8+ cores: WORKERS=cpu_count*2+1
_default_workers = max(2, multiprocessing.cpu_count())  # Mínimo 2
workers = int(os.getenv('WORKERS', _default_workers))
worker_class = "sync"
worker_connections = 100
max_requests = int(os.getenv('MAX_REQUESTS', '1000'))  # Reciclar worker después de N requests (evita memory leak)
max_requests_jitter = int(os.getenv('MAX_REQUESTS_JITTER', '100'))  # Jitter para distribuir reciclaje

# Timeout: aumentado a 180s para operaciones largas (reportes, imports)
# Si las requests tardan más: aumentar con TIMEOUT=300
timeout = int(os.getenv('TIMEOUT', '180'))
graceful_timeout = int(os.getenv('GRACEFUL_TIMEOUT', '30'))

# Logging — stdout/stderr para systemd journal; archivos si se prefiere.
# En producción: '-' = stdout (systemd capture); '/var/log/app/access.log' = archivo
# Formato para Apache reverse proxy: evitar duplicados en access.log
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel = os.getenv('LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'  # Incluye latencia (µs)

# Seguridad
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# Rendimiento
keepalive = 5
preload_app = False

# SSL (solo si NO usa Apache/Nginx para terminación SSL)
keyfile = os.getenv('SSL_KEYFILE')
certfile = os.getenv('SSL_CERTFILE')
ca_certs = os.getenv('SSL_CA_CERTS')

# Hooks
def when_ready(server):
    pid_file = os.getenv('GUNICORN_PID_FILE')
    if pid_file:
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

def on_exit(server):
    pid_file = os.getenv('GUNICORN_PID_FILE')
    if pid_file and os.path.exists(pid_file):
        os.remove(pid_file)
