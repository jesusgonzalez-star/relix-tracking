"""
Script para crear usuarios de prueba y datos de ejemplo
Ejecutar: python create_demo_user.py
"""

import pyodbc
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
import logging
import sys

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CONN_STR = (
    f"Driver={{{os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
    f"Server={os.getenv('DB_SERVER', '5CD5173D14\\SQLEXPRESS')};"
    f"Database={os.getenv('DB_NAME', 'Softland_Mock')};"
    f"Trusted_Connection={os.getenv('DB_TRUSTED_CONNECTION', 'yes')};"
)


def crear_roles():
    """Crea los roles base si no existen"""
    try:
        conn = pyodbc.connect(CONN_STR, timeout=10)
        cursor = conn.cursor()

        roles = ['ADMIN', 'BODEGA', 'CLIENTE']
        roles_created = []

        logger.info("Verificando roles...")

        for rol in roles:
            # Verificar si rol existe
            cursor.execute("SELECT Id FROM Roles WHERE Nombre = ?", (rol,))
            if not cursor.fetchone():
                # Insertar rol
                cursor.execute("""
                    INSERT INTO Roles (Nombre) VALUES (?)
                """, (rol,))
                roles_created.append(rol)
                logger.info(f"  ✓ Rol '{rol}' creado")
            else:
                logger.info(f"  ✓ Rol '{rol}' ya existe")

        conn.commit()
        cursor.close()
        conn.close()

        return True

    except pyodbc.Error as e:
        logger.error(f"Error de conexión al crear roles: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error creando roles: {str(e)}")
        return False


def crear_usuario_demo():
    """Crea usuarios de prueba para cada rol"""
    try:
        conn = pyodbc.connect(CONN_STR, timeout=10)
        cursor = conn.cursor()

        # Datos de usuarios demo
        usuarios_demo = [
            {
                'usuario': 'admin',
                'password': 'Admin123!',
                'nombre': 'Administrador Sistema',
                'email': 'admin@sistema.com',
                'rol': 'ADMIN'
            },
            {
                'usuario': 'bodega',
                'password': 'Bodega123!',
                'nombre': 'Trabajador Bodega',
                'email': 'bodega@sistema.com',
                'rol': 'BODEGA'
            },
            {
                'usuario': 'cliente',
                'password': 'Cliente123!',
                'nombre': 'Cliente Demo',
                'email': 'cliente@empresa.com',
                'rol': 'CLIENTE'
            }
        ]

        logger.info("Creando usuarios de demostración...")
        usuarios_creados = []

        for user_data in usuarios_demo:
            try:
                # Obtener ID de rol - MÁS ROBUSTO
                cursor.execute(
                    "SELECT Id FROM Roles WHERE Nombre = ?",
                    (user_data['rol'],)
                )
                rol_result = cursor.fetchone()

                if not rol_result:
                    logger.error(f"✗ Rol '{user_data['rol']}' NO EXISTE en la BD")
                    logger.error(f"  Verifica que db_setup.py se ejecutó correctamente")
                    continue

                rol_id = rol_result[0]

                # Verificar que el usuario no existe
                cursor.execute(
                    "SELECT Id FROM UsuariosSistema WHERE Usuario = ?",
                    (user_data['usuario'],)
                )

                if cursor.fetchone():
                    logger.warning(f"  ⚠ Usuario '{user_data['usuario']}' ya existe, omitiendo")
                    continue

                # Hashear contraseña
                password_hash = generate_password_hash(
                    user_data['password'],
                    method='pbkdf2:sha256'
                )

                # Insertar usuario - CON MEJOR VALIDACIÓN
                try:
                    cursor.execute("""
                        INSERT INTO UsuariosSistema
                        (Usuario, PasswordHash, NombreCompleto, Email, RolId, Activo)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """, (
                        user_data['usuario'],
                        password_hash,
                        user_data['nombre'],
                        user_data['email'],
                        rol_id
                    ))

                    conn.commit()
                    logger.info(f"  ✓ Usuario '{user_data['usuario']}' creado ({user_data['rol']})")
                    usuarios_creados.append(user_data['usuario'])

                except Exception as insert_error:
                    conn.rollback()
                    logger.error(f"  ✗ Error insertando usuario {user_data['usuario']}: {str(insert_error)}")

            except Exception as user_error:
                logger.error(f"  ✗ Error procesando usuario {user_data['usuario']}: {str(user_error)}")
                conn.rollback()

        cursor.close()
        conn.close()

        if usuarios_creados:
            logger.info("\n✅ Usuarios de demostración creados exitosamente")
            logger.info("\nCredenciales de prueba:")
            logger.info("=" * 60)
            for user in usuarios_demo:
                if user['usuario'] in usuarios_creados:
                    logger.info(f"Usuario: {user['usuario']:15} | Contraseña: {user['password']}")
            logger.info("=" * 60)
            return True
        else:
            logger.warning("⚠ No se crearon nuevos usuarios")
            return False

    except pyodbc.Error as e:
        logger.error(f"❌ Error de conexión a la BD: {str(e)}")
        logger.error("Verifica que SQL Server está ejecutándose y el .env está configurado")
        return False
    except Exception as e:
        logger.error(f"❌ Error general: {str(e)}")
        return False


def crear_cliente_demo():
    """Crea un cliente asociado a usuario cliente"""
    try:
        conn = pyodbc.connect(CONN_STR, timeout=10)
        cursor = conn.cursor()

        # Obtener ID del usuario cliente
        cursor.execute(
            "SELECT Id FROM UsuariosSistema WHERE Usuario = 'cliente'",
        )
        user_result = cursor.fetchone()

        if not user_result:
            logger.warning("Usuario 'cliente' no existe")
            return False

        user_id = user_result[0]

        # Verificar si ya existe cliente
        cursor.execute(
            "SELECT Id FROM Clientes WHERE UsuarioId = ?",
            (user_id,)
        )

        if cursor.fetchone():
            logger.info("Cliente ya existe para usuario")
            return True

        # Crear cliente
        cursor.execute("""
            INSERT INTO Clientes
            (UsuarioId, NombreEmpresa, RUT, Telefono, Activo)
            VALUES (?, ?, ?, ?, 1)
        """, (user_id, 'Empresa Demo S.A.', '12.345.678-K', '+56 2 2345 6789'))

        conn.commit()
        logger.info("✓ Cliente de demostración creado")
        cursor.close()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"Error creando cliente: {str(e)}")
        return False


def crear_productos_demo():
    """Crea productos de bodega de demostración"""
    try:
        conn = pyodbc.connect(CONN_STR, timeout=10)
        cursor = conn.cursor()

        productos_demo = [
            {'producto': 'PROD-001', 'desc': 'Producto Demo 1', 'stock': 50, 'ubicacion': 'A-01'},
            {'producto': 'PROD-002', 'desc': 'Producto Demo 2', 'stock': 30, 'ubicacion': 'B-02'},
            {'producto': 'PROD-003', 'desc': 'Producto Demo 3', 'stock': 20, 'ubicacion': 'C-03'},
        ]

        logger.info("Creando productos de demostración...")

        for prod in productos_demo:
            # Verificar si existe
            cursor.execute(
                "SELECT Id FROM ProductosBodega WHERE SoftlandProducto = ?",
                (prod['producto'],)
            )

            if cursor.fetchone():
                logger.info(f"Producto {prod['producto']} ya existe")
                continue

            cursor.execute("""
                INSERT INTO ProductosBodega
                (SoftlandProducto, Descripcion, StockActual, Ubicacion, Activo)
                VALUES (?, ?, ?, ?, 1)
            """, (prod['producto'], prod['desc'], prod['stock'], prod['ubicacion']))

            logger.info(f"✓ {prod['producto']}: {prod['desc']}")

        conn.commit()
        cursor.close()
        conn.close()

        logger.info("✅ Productos creados")
        return True

    except Exception as e:
        logger.error(f"Error creando productos: {str(e)}")
        return False


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("🔧 Creador de Datos de Demostración")
    logger.info("=" * 60)

    try:
        # PASO 1: Crear roles primero
        logger.info("\n[PASO 1/4] Creando roles...")
        if not crear_roles():
            logger.error("❌ No se pudieron crear los roles")
            sys.exit(1)

        # PASO 2: Crear usuarios
        logger.info("\n[PASO 2/4] Creando usuarios...")
        if not crear_usuario_demo():
            logger.error("❌ No se pudieron crear los usuarios")
            sys.exit(1)

        # PASO 3: Crear cliente
        logger.info("\n[PASO 3/4] Creando cliente de prueba...")
        crear_cliente_demo()

        # PASO 4: Crear productos
        logger.info("\n[PASO 4/4] Creando productos de demostración...")
        crear_productos_demo()

        logger.info("\n" + "=" * 60)
        logger.info("✨ TODO COMPLETADO - Listo para usar")
        logger.info("=" * 60)
        logger.info("\nAccede a: http://localhost:5000")
        logger.info("Con las credenciales mostradas arriba")

    except Exception as e:
        logger.error(f"❌ Error general: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
