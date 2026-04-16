#!/usr/bin/env python3
"""
Script de validación de configuración de base de datos para ODBC Driver 18.
Verifica que todos los parámetros estén correctamente configurados antes del despliegue.

Uso:
    python validate_db_config.py
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)


class ConfigValidator:
    """Validador de configuración para DB con ODBC Driver 18."""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def check_local_db_config(self):
        """Valida configuración de la base de datos local."""
        logger.info("=" * 70)
        logger.info("VALIDANDO: Base de Datos Local (Tracking/Usuarios)")
        logger.info("=" * 70)

        local_server = os.environ.get('LOCAL_SERVER')
        local_db_name = os.environ.get('LOCAL_DB_NAME')
        local_db_user = os.environ.get('LOCAL_DB_USER', '').strip()
        local_db_pass = os.environ.get('LOCAL_DB_PASS', '').strip()
        local_db_driver = os.environ.get('LOCAL_DB_DRIVER', '')
        local_db_encrypt = os.environ.get('LOCAL_DB_ENCRYPT', '').lower()
        local_db_trust_cert = os.environ.get('LOCAL_DB_TRUST_CERT', '').lower()

        # Validaciones
        if not local_server:
            self.errors.append("❌ LOCAL_SERVER no está definido")
        else:
            logger.info(f"✓ LOCAL_SERVER: {local_server}")

        if not local_db_name:
            self.errors.append("❌ LOCAL_DB_NAME no está definido")
        else:
            logger.info(f"✓ LOCAL_DB_NAME: {local_db_name}")

        if not local_db_user:
            self.warnings.append("⚠ LOCAL_DB_USER no está definido (OK si uses Trusted_Connection en Windows)")
        else:
            logger.info(f"✓ LOCAL_DB_USER: {local_db_user}")

        if not local_db_pass:
            self.warnings.append("⚠ LOCAL_DB_PASS no está definido (OK si no requiere autenticación SQL)")
        else:
            logger.info(f"✓ LOCAL_DB_PASS: [DEFINIDA]")

        if not local_db_driver:
            self.warnings.append("⚠ LOCAL_DB_DRIVER no está definido (usando default)")
            logger.info(f"  → LOCAL_DB_DRIVER: ODBC Driver 17 for SQL Server (default)")
        else:
            logger.info(f"✓ LOCAL_DB_DRIVER: {local_db_driver}")

            if 'Driver 18' in local_db_driver:
                logger.info("  → Driver 18 detectado: validando parámetros de seguridad")

                # Validar Encrypt
                valid_encrypt = ('yes', 'no', 'optional', 'mandatory')
                if not local_db_encrypt:
                    self.warnings.append(f"⚠ LOCAL_DB_ENCRYPT no está definido (usando default: 'no')")
                    logger.info(f"  → LOCAL_DB_ENCRYPT: no (default)")
                elif local_db_encrypt not in valid_encrypt:
                    self.errors.append(f"❌ LOCAL_DB_ENCRYPT='{local_db_encrypt}' es inválido. Use: {', '.join(valid_encrypt)}")
                else:
                    logger.info(f"✓ LOCAL_DB_ENCRYPT: {local_db_encrypt}")

                # Validar TrustServerCertificate
                valid_trust = ('yes', 'no', 'true', 'false')
                if not local_db_trust_cert:
                    self.warnings.append(f"⚠ LOCAL_DB_TRUST_CERT no está definido (usando default: 'yes')")
                    logger.info(f"  → LOCAL_DB_TRUST_CERT: yes (default)")
                elif local_db_trust_cert not in valid_trust:
                    self.errors.append(f"❌ LOCAL_DB_TRUST_CERT='{local_db_trust_cert}' es inválido. Use: {', '.join(valid_trust)}")
                else:
                    logger.info(f"✓ LOCAL_DB_TRUST_CERT: {local_db_trust_cert}")
                    if local_db_trust_cert in ('yes', 'true'):
                        logger.info("  → Aceptará certificados autofirmados (recomendado para redes corporativas)")

    def check_softland_config(self):
        """Valida configuración del ERP Softland."""
        logger.info("")
        logger.info("=" * 70)
        logger.info("VALIDANDO: ERP Softland (Solo Lectura)")
        logger.info("=" * 70)

        db_server = os.environ.get('DB_SERVER')
        db_name = os.environ.get('DB_NAME')
        db_user = os.environ.get('DB_USER')
        db_pass = os.environ.get('DB_PASS', '').strip()
        db_driver = os.environ.get('DB_DRIVER', '')
        db_encrypt = os.environ.get('SOFTLAND_ENCRYPT', '').lower()
        db_trust_cert = os.environ.get('SOFTLAND_TRUST_CERT', '').lower()

        if not db_server:
            self.errors.append("❌ DB_SERVER no está definido")
        else:
            logger.info(f"✓ DB_SERVER: {db_server}")

        if not db_name:
            self.errors.append("❌ DB_NAME no está definido")
        else:
            logger.info(f"✓ DB_NAME: {db_name}")

        if not db_user:
            self.errors.append("❌ DB_USER no está definido")
        else:
            logger.info(f"✓ DB_USER: {db_user}")

        if not db_pass:
            self.errors.append("❌ DB_PASS no está definido")
        else:
            logger.info(f"✓ DB_PASS: [DEFINIDA]")

        if not db_driver:
            self.warnings.append("⚠ DB_DRIVER no está definido (usando default)")
            logger.info(f"  → DB_DRIVER: ODBC Driver 17 for SQL Server (default)")
        else:
            logger.info(f"✓ DB_DRIVER: {db_driver}")

            if 'Driver 18' in db_driver:
                logger.info("  → Driver 18 detectado: validando parámetros de seguridad")

                valid_encrypt = ('yes', 'no', 'optional', 'mandatory')
                if not db_encrypt:
                    self.warnings.append(f"⚠ SOFTLAND_ENCRYPT no está definido (usando default: 'no')")
                    logger.info(f"  → SOFTLAND_ENCRYPT: no (default)")
                elif db_encrypt not in valid_encrypt:
                    self.errors.append(f"❌ SOFTLAND_ENCRYPT='{db_encrypt}' es inválido. Use: {', '.join(valid_encrypt)}")
                else:
                    logger.info(f"✓ SOFTLAND_ENCRYPT: {db_encrypt}")

                valid_trust = ('yes', 'no', 'true', 'false')
                if not db_trust_cert:
                    self.warnings.append(f"⚠ SOFTLAND_TRUST_CERT no está definido (usando default: 'yes')")
                    logger.info(f"  → SOFTLAND_TRUST_CERT: yes (default)")
                elif db_trust_cert not in valid_trust:
                    self.errors.append(f"❌ SOFTLAND_TRUST_CERT='{db_trust_cert}' es inválido. Use: {', '.join(valid_trust)}")
                else:
                    logger.info(f"✓ SOFTLAND_TRUST_CERT: {db_trust_cert}")

    def check_production_config(self):
        """Valida configuración de producción."""
        logger.info("")
        logger.info("=" * 70)
        logger.info("VALIDANDO: Configuración de Producción")
        logger.info("=" * 70)

        debug = os.environ.get('DEBUG', 'False').lower() == 'true'
        secret_key = (os.environ.get('SECRET_KEY') or '').strip()
        api_secret = (os.environ.get('API_SECRET') or '').strip()

        if debug:
            logger.info("ℹ DEBUG=True (modo desarrollo)")
        else:
            logger.info("✓ DEBUG=False (modo producción)")

            # En producción, validar secrets
            if not secret_key:
                self.errors.append("❌ SECRET_KEY no está definido (obligatorio en producción)")
            else:
                logger.info(f"✓ SECRET_KEY: [DEFINIDA]")

            if not api_secret:
                self.errors.append("❌ API_SECRET no está definido (obligatorio en producción)")
            else:
                logger.info(f"✓ API_SECRET: [DEFINIDA]")

        # Validar requerimiento de autenticación SQL en BD local
        local_db_require_sql_auth = os.environ.get('LOCAL_DB_REQUIRE_SQL_AUTH', '').lower() == 'true'
        if not debug and local_db_require_sql_auth:
            local_db_user = (os.environ.get('LOCAL_DB_USER') or '').strip()
            local_db_pass = (os.environ.get('LOCAL_DB_PASS') or '').strip()

            if not local_db_user or not local_db_pass:
                self.errors.append(
                    "❌ LOCAL_DB_REQUIRE_SQL_AUTH=true pero LOCAL_DB_USER y/o LOCAL_DB_PASS no están definidos"
                )

    def check_driver_installation(self):
        """Verifica que el driver ODBC esté disponible."""
        logger.info("")
        logger.info("=" * 70)
        logger.info("VALIDANDO: Disponibilidad del Driver ODBC")
        logger.info("=" * 70)

        try:
            import pyodbc
            drivers = pyodbc.drivers()
            logger.info(f"✓ pyodbc disponible (versión: {pyodbc.version})")
            logger.info(f"✓ Drivers ODBC instalados:")
            for driver in drivers:
                logger.info(f"  - {driver}")

            # Verificar Driver 18
            driver_18_found = any('Driver 18' in d for d in drivers)
            driver_17_found = any('Driver 17' in d for d in drivers)

            if driver_18_found:
                logger.info("✓ ODBC Driver 18 for SQL Server encontrado")
            elif driver_17_found:
                logger.info("⚠ ODBC Driver 18 no encontrado, pero Driver 17 está disponible")
            else:
                self.warnings.append("⚠ No se encontró ningún Microsoft ODBC Driver para SQL Server")

        except ImportError:
            self.errors.append("❌ pyodbc no está instalado. Instala con: pip install pyodbc")
        except Exception as e:
            self.errors.append(f"❌ Error al verificar drivers ODBC: {e}")

    def run(self):
        """Ejecuta todas las validaciones."""
        logger.info("\n")
        logger.info("╔" + "=" * 68 + "╗")
        logger.info("║" + "VALIDADOR DE CONFIGURACIÓN ODBC DRIVER 18".center(68) + "║")
        logger.info("╚" + "=" * 68 + "╝")
        logger.info("")

        self.check_local_db_config()
        self.check_softland_config()
        self.check_production_config()
        self.check_driver_installation()

        # Resumen
        logger.info("")
        logger.info("=" * 70)
        logger.info("RESUMEN")
        logger.info("=" * 70)

        if self.errors:
            logger.error(f"\n❌ Se encontraron {len(self.errors)} ERROR(es):\n")
            for error in self.errors:
                logger.error(f"  {error}")

        if self.warnings:
            logger.warning(f"\n⚠ Se encontraron {len(self.warnings)} ADVERTENCIA(s):\n")
            for warning in self.warnings:
                logger.warning(f"  {warning}")

        if not self.errors and not self.warnings:
            logger.info("\n✓ ¡Configuración válida! La aplicación debería conectarse sin problemas.")
        elif not self.errors:
            logger.info("\n⚠ La configuración tiene advertencias, pero podría funcionar.")
        else:
            logger.error("\n❌ La configuración tiene errores críticos. Corrígelos antes de desplegar.")
            sys.exit(1)

        logger.info("")


if __name__ == '__main__':
    validator = ConfigValidator()
    validator.run()
