import os
import multiprocessing

# Configuración del servidor Gunicorn para producción

# Binding
bind = f"0.0.0.0:{os.getenv('PORT', 5000)}"

# Workers
workers = os.getenv('WORKERS', multiprocessing.cpu_count() * 2 + 1)
worker_class = "sync"
worker_connections = 100
max_requests = 1000
max_requests_jitter = 100

# Timeout
timeout = 120
graceful_timeout = 30

# Logging
accesslog = "access.log"
errorlog = "error.log"
loglevel = os.getenv('LOG_LEVEL', 'info')

# Seguridad
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# Rendimiento
keepalive = 5
preload_app = False

# SSL (descomentar en producción con certificados)
# keyfile = "/path/to/keyfile.key"
# certfile = "/path/to/certfile.crt"
# ca_certs = "/path/to/ca.pem"
# ssl_version = "TLSv1_2"

# Hook para logging personalizado
def when_ready(server):
    open("gunicorn.pid", "w").write(str(os.getpid()))

def on_exit(server):
    import os
    if os.path.exists("gunicorn.pid"):
        os.remove("gunicorn.pid")
