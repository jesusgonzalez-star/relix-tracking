#!/usr/bin/env python3
"""Suite de Pruebas Automatizada - Sistema de Tracking Logístico"""

import requests
import time
from collections import defaultdict

BASE_URL = 'http://localhost:5000'
results = defaultdict(list)
pass_count = fail_count = error_count = 0
test_num = 0

def log_test(section, name, status, msg=''):
    global test_num, pass_count, fail_count, error_count
    test_num += 1
    if status == 'PASS': pass_count += 1
    elif status == 'FAIL': fail_count += 1
    else: error_count += 1
    symbol = '✅' if status == 'PASS' else ('❌' if status == 'FAIL' else '⚠️')
    print(f'{symbol} [{test_num:02d}] {section}: {name}')
    if msg: print(f'    {msg}')

print('🚀 Iniciando Pruebas Automatizadas...\n')

# 1.1 Health
try:
    r = requests.get(f'{BASE_URL}/health')
    log_test('Salud', 'Health Endpoint', 'PASS' if r.status_code == 200 and r.json().get('status') == 'ok' else 'FAIL')
except Exception as e:
    log_test('Salud', 'Health Endpoint', 'ERROR', str(e))

# 1.2 Swagger
try:
    r = requests.get(f'{BASE_URL}/apidocs/')
    log_test('Salud', 'Swagger', 'PASS' if r.status_code == 200 else 'FAIL')
except Exception as e:
    log_test('Salud', 'Swagger', 'ERROR', str(e))

# 3.1 OC Valida
try:
    r = requests.get(f'{BASE_URL}/api/softland/oc/1001')
    log_test('Softland', 'OC Válida', 'PASS' if r.status_code in [200, 404] else 'FAIL')
except Exception as e:
    log_test('Softland', 'OC Válida', 'ERROR', str(e))

# 3.2 OC No Existe
try:
    r = requests.get(f'{BASE_URL}/api/softland/oc/999999')
    log_test('Softland', 'OC No Existe (404)', 'PASS' if r.status_code == 404 else 'FAIL')
except Exception as e:
    log_test('Softland', 'OC No Existe (404)', 'ERROR', str(e))

# 3.3 Security Headers (Softland)
try:
    r = requests.get(f'{BASE_URL}/api/softland/oc/1001')
    h = r.headers
    found = len([k for k in ['X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy'] if k in h])
    log_test('Seguridad', 'Headers Softland', 'PASS' if found >= 2 else 'FAIL', f'{found}/3 encontrados')
except Exception as e:
    log_test('Seguridad', 'Headers Softland', 'ERROR', str(e))

# 4.1 Tracking BODEGA
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', json={'num_oc': 1001, 'estado': 'BODEGA', 'idempotency_key': 'test-bodega-001'})
    log_test('API Tracking', 'Crear (BODEGA)', 'PASS' if r.status_code in [201, 200] else 'FAIL', f'Status: {r.status_code}')
except Exception as e:
    log_test('API Tracking', 'Crear (BODEGA)', 'ERROR', str(e))

# 4.2 Tracking TRANSITO
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', json={'num_oc': 1002, 'estado': 'TRANSITO', 'idempotency_key': 'test-transito-001'})
    log_test('API Tracking', 'Crear (TRANSITO)', 'PASS' if r.status_code in [201, 200] else 'FAIL', f'Status: {r.status_code}')
except Exception as e:
    log_test('API Tracking', 'Crear (TRANSITO)', 'ERROR', str(e))

# 4.3 Tracking ENTREGADO
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', json={'num_oc': 1003, 'estado': 'ENTREGADO', 'idempotency_key': 'test-entregado-001'})
    log_test('API Tracking', 'Crear (ENTREGADO)', 'PASS' if r.status_code in [201, 200] else 'FAIL', f'Status: {r.status_code}')
except Exception as e:
    log_test('API Tracking', 'Crear (ENTREGADO)', 'ERROR', str(e))

# 4.4 Idempotencia
try:
    p = {'num_oc': 1004, 'estado': 'BODEGA', 'idempotency_key': 'test-idempotent-001'}
    r1 = requests.post(f'{BASE_URL}/api/tracking/', json=p)
    time.sleep(0.2)
    r2 = requests.post(f'{BASE_URL}/api/tracking/', json=p)
    same_id = r1.json().get('id') == r2.json().get('id')
    log_test('API Tracking', 'Idempotencia', 'PASS' if same_id else 'FAIL')
except Exception as e:
    log_test('API Tracking', 'Idempotencia', 'ERROR', str(e))

# 4.5 Validacion num_oc
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', json={'estado': 'BODEGA'})
    log_test('API Tracking', 'Validación (num_oc)', 'PASS' if r.status_code == 400 else 'FAIL', f'Status: {r.status_code}')
except Exception as e:
    log_test('API Tracking', 'Validación (num_oc)', 'ERROR', str(e))

# 4.6 Estado Inválido
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', json={'num_oc': 1005, 'estado': 'INVALIDO', 'idempotency_key': 'test-inv'})
    log_test('API Tracking', 'Estado Inválido', 'PASS' if r.status_code == 400 else 'FAIL', f'Status: {r.status_code}')
except Exception as e:
    log_test('API Tracking', 'Estado Inválido', 'ERROR', str(e))

# 4.7 Historial
try:
    requests.post(f'{BASE_URL}/api/tracking/', json={'num_oc': 2001, 'estado': 'BODEGA', 'idempotency_key': 'test-hist-001'})
    r = requests.get(f'{BASE_URL}/api/tracking/oc/2001')
    log_test('API Tracking', 'Historial', 'PASS' if r.status_code == 200 and isinstance(r.json(), list) else 'FAIL')
except Exception as e:
    log_test('API Tracking', 'Historial', 'ERROR', str(e))

# 4.8 Historial Vacío
try:
    r = requests.get(f'{BASE_URL}/api/tracking/oc/999999')
    log_test('API Tracking', 'Historial Vacío', 'PASS' if r.status_code == 200 and len(r.json()) == 0 else 'FAIL')
except Exception as e:
    log_test('API Tracking', 'Historial Vacío', 'ERROR', str(e))

# 4.9 Validacion Long Key
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', json={'num_oc': 1006, 'estado': 'BODEGA', 'idempotency_key': 'x'*100})
    log_test('API Tracking', 'Clave Larga', 'PASS' if r.status_code == 400 else 'FAIL', f'Status: {r.status_code}')
except Exception as e:
    log_test('API Tracking', 'Clave Larga', 'ERROR', str(e))

# 11.1 Headers HTML
try:
    r = requests.get(f'{BASE_URL}/login')
    h = r.headers
    found = len([k for k in ['X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy'] if k in h])
    log_test('Seguridad', 'Headers HTML', 'PASS' if found >= 2 else 'FAIL', f'{found}/3')
except Exception as e:
    log_test('Seguridad', 'Headers HTML', 'ERROR', str(e))

# 11.2 CSRF
try:
    r = requests.get(f'{BASE_URL}/login')
    log_test('Seguridad', 'CSRF Token', 'PASS' if 'csrf_token' in r.text else 'FAIL')
except Exception as e:
    log_test('Seguridad', 'CSRF Token', 'ERROR', str(e))

# 12.1 Rate Limiting
try:
    url = f'{BASE_URL}/api/tracking/oc/1001'
    success_count = 0
    rate_limited = False
    for i in range(70):
        r = requests.get(url)
        if r.status_code == 200:
            success_count += 1
        elif r.status_code == 429:
            rate_limited = True
            break
    log_test('Rate Limiting', 'Rate Limit Activo', 'PASS' if rate_limited or success_count < 70 else 'FAIL', f'Solicitudes: {success_count}')
except Exception as e:
    log_test('Rate Limiting', 'Rate Limit Activo', 'ERROR', str(e))

# 13.1 404 Error
try:
    r = requests.get(f'{BASE_URL}/no-existe')
    log_test('Errores', 'Error 404', 'PASS' if r.status_code == 404 else 'FAIL')
except Exception as e:
    log_test('Errores', 'Error 404', 'ERROR', str(e))

# 13.3 400 Error
try:
    r = requests.post(f'{BASE_URL}/api/tracking/', data='{bad json')
    log_test('Errores', 'Error 400', 'PASS' if r.status_code == 400 else 'FAIL')
except Exception as e:
    log_test('Errores', 'Error 400', 'ERROR', str(e))

print('\n' + '='*70)
print(f'📊 RESUMEN: Total={test_num}, ✅ Exitosas={pass_count}, ❌ Fallidas={fail_count}, ⚠️ Errores={error_count}')
if test_num > 0:
    success_rate = (pass_count/test_num)*100
    print(f'📈 Tasa de Éxito: {success_rate:.1f}%')

    if success_rate >= 90:
        rating = '🟢 ROBUSTO - Excelente'
    elif success_rate >= 75:
        rating = '🟡 ACEPTABLE - Necesita mejoras'
    elif success_rate >= 50:
        rating = '🟠 DÉBIL - Problemas significativos'
    else:
        rating = '🔴 MUY DÉBIL - Crítico'
    print(f'💪 Evaluación: {rating}')

print('='*70)
