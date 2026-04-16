import os
import multiprocessing

# Configuración del servidor Gunicorn para producción (Linux)
# En Windows dev se usa app.run() directamente; este archivo solo aplica en Linux.

# Binding — 127.0.0.1 para uso detrás de Apache/Nginx reverse proxy.
# Para exponer directo (sin proxy), cambie GUNICORN_BIND=0.0.0.0:<port> en entorno.
bind = os.getenv('GUNICORN_BIND', f"127.0.0.1:{os.getenv('PORT', 5000)}")

# Workers
workers = int(os.getenv('WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
worker_connections = 100
max_requests = 1000
max_requests_jitter = 100

# Timeout
timeout = 120
graceful_timeout = 30

# Logging — stdout/stderr para systemd journal; archivos si se prefiere.
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel = os.getenv('LOG_LEVEL', 'info')

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
