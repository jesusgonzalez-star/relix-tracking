# 🔐 Guía de Seguridad

## Resumen de Mejoras de Seguridad Implementadas

### ✅ Ya Implementado

1. **Autenticación**
   - ✅ Hashing PBKDF2-SHA256 con salt de 16 bytes
   - ✅ Validación de credenciales sin exposición de datos
   - ✅ Session con timeouts y cookies seguras
   - ✅ Decorator `@login_required` con verificación de roles

2. **Encriptación**
   - ✅ HTTPS ready (SESSION_COOKIE_SECURE)
   - ✅ Conexión a BD con encriptación

3. **Inyección SQL**
   - ✅ Parámetros seguros en TODAS las queries (?)
   - ✅ No concatenación de strings en SQL

4. **XSS (Cross-Site Scripting)**
   - ✅ Sanitización de entrada
   - ✅ Escape de salida en templates
   - ✅ SAMESITE cookies

5. **CSRF (Cross-Site Request Forgery)**
   - ✅ Atributo SAMESITE en cookies
   - ✅ Sessions aseguradas

6. **Validación**
   - ✅ Validación de email
   - ✅ Validación de usuario
   - ✅ Validación de archivo uploads
   - ✅ Sanitización de texto

7. **Control de Acceso**
   - ✅ Roles y permisos por ruta
   - ✅ Verificación de autorización
   - ✅ Logging de intentos denegados

8. **Gestión de Archivos**
   - ✅ Extensiones permitidas whitelist
   - ✅ Nombres seguros con `secure_filename`
   - ✅ Límite de tamaño (16MB)
   - ✅ Directorio de uploads separado

9. **Logging y Auditoría**
   - ✅ Logging completo de eventos
   - ✅ Registro de intentos fallidos
   - ✅ Trazabilidad de cambios

10. **Manejo de Errores**
    - ✅ Mensajes genéricos sin exposición de datos
    - ✅ Error handlers globales

---

## 📋 Checklist de Seguridad en Producción

### Antes de Deployar

- [ ] **Cambiar SECRET_KEY**
  ```bash
  # Generar nueva clave
  python -c "import os; print(os.urandom(32).hex())"
  # Guardar en .env
  ```

- [ ] **Configurar HTTPS**
  ```
  # En .env
  SESSION_COOKIE_SECURE=True
  DEBUG=False
  ```

- [ ] **Variable DEBUG=False**
  ```
  DEBUG=False
  ```

- [ ] **Contraseña de admin fuerte**
  ```bash
  # Cambiar contraseña admin por una segura (12+ caracteres, mayús, minús, números, símbolos)
  ```

- [ ] **Permisos de carpetas**
  ```bash
  # Linux/Mac
  chmod 750 static/uploads
  chmod 600 .env
  
  # Windows: Properties > Security > Everyone > Remove
  ```

- [ ] **Certificado SSL/TLS**
  - Comprar o generar certificado válido
  - Configurar en servidor (nginx, Apache, etc)

- [ ] **Firewall**
  - [ ] Solo puerto 443 (HTTPS) abierto
  - [ ] Puerto 5000 bloqueado (solo local)
  - [ ] SSH en puerto no-estándar

- [ ] **Rate Limiting** (opcional pero recomendado)
  ```bash
  pip install Flask-Limiter
  ```

- [ ] **WAF** (Web Application Firewall)
  - Considerar Cloudflare, AWS WAF, etc.

- [ ] **Backup automático**
  - [ ] Base de datos: Diario
  - [ ] Archivos de usuario: Diario
  - [ ] Logs: Semanal
  - [ ] Almacenamiento seguro (encriptado)

---

## 🚨 Vulnerabilidades Comunes y Mitigaciones

### 1. SQL Injection
**Status**: ✅ Mitigado
- Todas las queries usan parámetros (?)
- Nunca concatenar strings en SQL

**Verificar:**
```bash
grep -r "format(" app.py  # Buscar format strings (peligroso)
grep -r "f\"SELECT" app.py  # Buscar f-strings en SQL (peligroso)
```

### 2. Cross-Site Scripting (XSS)
**Status**: ✅ Mitigado
- Sanitización de entrada
- Encoding de salida

**Verificar:**
```bash
# Probar en navegador
# Campo de entrada: <script>alert('xss')</script>
# No debe ejecutar
```

### 3. CSRF
**Status**: ✅ Mitigado
- Flask-Session con SAMESITE=Lax

### 4. Fuerza Bruta (Login)
**Status**: ⚠️ Parcialmente mitigado
- Se registran intentos fallidos
- **Recomendación**: Agregar Flask-Limiter

```bash
pip install Flask-Limiter

# En app.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(app, key_func=get_remote_address)

@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")  # Max 5 intentos por minuto
def login():
    # ...
```

### 5. Aseguración de Credenciales
**Status**: ✅ Mitigado
- Hashing PBKDF2-SHA256
- Nunca guardar plaintext

### 6. Exposición de Datos Sensibles
**Status**: ✅ Mitigado
- Mensajes de error genéricos
- No exponer stack traces en producción
- Logging seguro

### 7. Actualización de Dependencias
**Status**: ⚠️ Revisar regularmente

```bash
# Chequear vulnerabilidades
pip install safety
safety check

# Actualizar paquetes
pip install --upgrade -r requirements.txt
```

---

## 🔍 Auditoría de Seguridad

### Revisar logs regularmente

```bash
# Ver últimos logins
grep "Login exitoso" app.log

# Ver intentos fallidos
grep "fallido" app.log

# Ver accesos denegados
grep "Acceso denegado" app.log

# Ver errores
grep "ERROR" app.log
```

### Monitoreo en tiempo real

```bash
# Terminal 1: Ver logs en vivo
tail -f app.log

# Terminal 2: Usar la aplicación
# Observar qué se registra en tiempo real
```

---

## 🛡️ Prácticas Recomendadas

### 1. Gestión de Contraseñas
- [ ] Implementar política de cambio cada 90 días
- [ ] Mínimo 12 caracteres
- [ ] Requiere mayúscula, minúscula, número, símbolo
- [ ] No permitir reutilización de últimas 5 contraseñas

### 2. Acceso Administrativo
- [ ] Usuario admin diferente al de desarrollo
- [ ] 2FA para admin (Two-Factor Authentication)
- [ ] Auditoría completa de acciones admin

### 3. Datos de Usuario
- [ ] Encriptar datos sensibles en BD
- [ ] GDPR compliance (derecho al olvido)
- [ ] Política de privacidad visible
- [ ] Consentimiento informado

### 4. Transportista y Geolocalización
- [ ] Avisar usuario que se registra geolocalización
- [ ] Solo guardar cuando usuario lo autoriza
- [ ] GDPR compliance

### 5. Backups y Recuperación
- [ ] Backup diario de BD
- [ ] Verificar que backups sean restaurables
- [ ] Guardar en ubicación segura (cloud encriptado)
- [ ] Plan de recuperación ante desastres

### 6. Monitoreo y Alertas
- [ ] Alertas para múltiples intentos de login fallidos
- [ ] Alertas para accesos desde IPs nuevas
- [ ] Monitoreo de uso de ancho de banda
- [ ] Monitoreo de espacio en disco

---

## 🔒 Seguridad en Diferentes Ambientes

### Desarrollo
```
DEBUG=True
SESSION_COOKIE_SECURE=False
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Testing
```
DEBUG=False
SESSION_COOKIE_SECURE=False
ALLOWED_HOSTS=localhost,testing-server
DATABASE=test_db
```

### Producción
```
DEBUG=False
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Strict
ALLOWED_HOSTS=tu-dominio.com,www.tu-dominio.com
HTTPS_ONLY=True
```

---

## ⚙️ Configuración de Servidor (Nginx + Gunicorn)

```nginx
# /etc/nginx/sites-available/app

upstream app {
    server 127.0.0.1:5000 fail_timeout=0;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name tu-dominio.com;

    ssl_certificate /etc/ssl/certs/tu-dominio.crt;
    ssl_certificate_key /etc/ssl/private/tu-dominio.key;
    
    # Seguridad SSL
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Límite de rate
    limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
    
    location /login {
        limit_req zone=login burst=5 nodelay;
        proxy_pass http://app;
    }

    location / {
        proxy_pass http://app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Headers de seguridad
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}

# Redirect HTTP a HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name tu-dominio.com;
    return 301 https://$server_name$request_uri;
}
```

---

## 📞 Reporte de Vulnerabilidades

Si encuentras una vulnerabilidad:
1. **NO publiques en social media**
2. Contacta a: security@tu-empresa.com
3. Proporciona detalles técnicos
4. Espera confirmación antes de divulgar

---

## ✅ Próximas Auditorías

- [ ] Mensual: Revisar logs de acceso
- [ ] Trimestral: Auditoria de código
- [ ] Semestral: Prueba de penetración
- [ ] Anual: Revisión completa de seguridad

---

**Versión**: 2.0 - Completamente Mejorada  
**Última revisión**: 2026-03-17
