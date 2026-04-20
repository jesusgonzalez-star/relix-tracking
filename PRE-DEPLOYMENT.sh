#!/bin/bash
# SCRIPT: PRE-DEPLOYMENT CHECKLIST (sábado)
# Ejecutar esto ANTES del lunes

echo "================================"
echo "PRE-DEPLOYMENT CHECKLIST"
echo "================================"
echo ""

# 1. Verificar código
echo "1. Revisando código..."
if [ -f "app.py" ] && [ -f "config.py" ] && [ -f "wsgi.py" ]; then
    echo "   ✅ Archivos principales presentes"
else
    echo "   ❌ FALTA algún archivo crítico"
    exit 1
fi

# 2. Verificar .env.example
echo "2. Revisando .env.example..."
if [ -f ".env.example" ]; then
    echo "   ✅ .env.example existe"
    echo "   ⚠️  RECORDAR: Copiar a .env el lunes y llenar secretos"
else
    echo "   ❌ .env.example NO existe"
fi

# 3. Verificar requirements.txt
echo "3. Revisando requirements.txt..."
if [ -f "requirements.txt" ]; then
    echo "   ✅ requirements.txt existe"
    grep -q "Flask\|SQLAlchemy\|gunicorn" requirements.txt
    if [ $? -eq 0 ]; then
        echo "   ✅ Dependencias principales presentes"
    fi
else
    echo "   ⚠️  requirements.txt no encontrado (CREAR antes de deploy)"
fi

# 4. Datos para el lunes
echo ""
echo "================================"
echo "INFORMACIÓN PARA EL LUNES:"
echo "================================"
echo ""
echo "Copiar esta información:"
echo "  • Usuario de Softland: JGonzalez"
echo "  • Servidor Softland: RELIX-SQL01\SOFTLAND"
echo "  • BD Softland: ZDESARROLLO02"
echo ""
echo "Necesitarás generar (en Python):"
echo "  SECRET_KEY: python3 -c \"import os; print(os.urandom(32).hex())\""
echo "  API_SECRET: python3 -c \"import os; print(os.urandom(32).hex())\""
echo ""
echo "Dominio para HTTPS:"
echo "  • ¿Cuál es el dominio? (ej: tracking.tudominio.com)"
echo ""

