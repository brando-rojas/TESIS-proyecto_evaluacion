# seed_data.py

import logging
from sqlalchemy.exc import IntegrityError

# --- Importar app, db y modelos necesarios ---
try:
    # Asumiendo estructura con app.py en la raíz
    from app import app, db
    from models import TipoAnalisis, HerramientaAnalisis
    # Si usas el patrón factory con paquete 'app'
    # from app import create_app, db
    # from app.models import TipoAnalisis, HerramientaAnalisis
    # app = create_app() # Crear instancia para el contexto
except ImportError as e:
    print(f"Error importando app/db/modelos: {e}")
    print("Asegúrate de que las importaciones sean correctas para tu estructura.")
    exit(1)

# Configurar logging básico para el script
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

# --- Datos a Poblar ---

TIPOS_ANALISIS = [
    {"nombre": "Formato y Estilo"},
    {"nombre": "Métricas de Código"},
    {"nombre": "Similitud de Código"},
    {"nombre": "Análisis Estático General"}, # Para herramientas como ClangTidy
    # Añade otros tipos si los necesitas
]

HERRAMIENTAS = [
    # --- Python ---
    {
        "nombre": "flake8", # ID interno
        "nombre_mostrado": "Flake8 (PEP8 Estándar)", # Para UI
        "lenguaje": "python",
        "tipo_nombre": "Formato y Estilo", # Nombre del TipoAnalisis
        "descripcion": "Verifica el cumplimiento de PEP8, errores lógicos básicos (PyFlakes) y complejidad (McCabe)."
    },
    {
        "nombre": "pylint",
        "nombre_mostrado": "Pylint (Extensivo)",
        "lenguaje": "python",
        "tipo_nombre": "Formato y Estilo", # También puede ser 'Análisis Estático General'
        "descripcion": "Análisis más profundo de estilo, errores, convenciones y refactorización. Requiere más configuración."
    },
    {
        "nombre": "black-check", # Usar nombre distinto si black format es otra opción
        "nombre_mostrado": "Black (Verificar Formato)",
        "lenguaje": "python",
        "tipo_nombre": "Formato y Estilo",
        "descripcion": "Verifica si el código cumple con el formato 'opinado' de Black, sin modificarlo."
    },
    # Podrías añadir 'black-format' como otra herramienta si quieres ofrecer auto-formateo
    # {
    #    "nombre": "black-format",
    #    "nombre_mostrado": "Black (Auto-Formatear)",
    #    "lenguaje": "python",
    #    "tipo_nombre": "Formato y Estilo",
    #    "descripcion": "Aplica automáticamente el formato 'opinado' de Black."
    # },

    # --- C / C++ ---
    {
        "nombre": "clang-format-google",
        "nombre_mostrado": "ClangFormat (Estilo Google)",
        "lenguaje": "c", # Aplica a C y C++
        "tipo_nombre": "Formato y Estilo",
        "descripcion": "Verifica el formato según la guía de estilo de Google (usando clang-format --dry-run)."
    },
    {
        "nombre": "clang-format-llvm",
        "nombre_mostrado": "ClangFormat (Estilo LLVM)",
        "lenguaje": "c",
        "tipo_nombre": "Formato y Estilo",
        "descripcion": "Verifica el formato según la guía de estilo de LLVM (usando clang-format --dry-run)."
    },
    {
        "nombre": "clang-format-webkit",
        "nombre_mostrado": "ClangFormat (Estilo WebKit)",
        "lenguaje": "c",
        "tipo_nombre": "Formato y Estilo",
        "descripcion": "Verifica el formato según la guía de estilo de WebKit (usando clang-format --dry-run)."
    },
    # ClangTidy es más complejo, requiere flags de compilación
    # {
    #    "nombre": "clang-tidy-default",
    #    "nombre_mostrado": "ClangTidy (Checks Predeterminados)",
    #    "lenguaje": "c",
    #    "tipo_nombre": "Análisis Estático General",
    #    "descripcion": "Ejecuta análisis estático más profundo con ClangTidy. Puede requerir configuración de compilación."
    # },
]

def seed_data():
    """Puebla las tablas TipoAnalisis y HerramientaAnalisis."""
    log.info("Iniciando proceso de seed para Tipos y Herramientas de Análisis...")

    # Usar el contexto de la aplicación
    with app.app_context():

        # --- Poblar TipoAnalisis ---
        tipos_existentes = {t.nombre: t.id for t in TipoAnalisis.query.all()}
        tipos_mapeados = {} # Guardar IDs generados/existentes
        tipos_added_count = 0

        print("\n--- Poblando TipoAnalisis ---")
        for tipo_data in TIPOS_ANALISIS:
            nombre = tipo_data["nombre"]
            if nombre in tipos_existentes:
                print(f"  Tipo '{nombre}' ya existe (ID: {tipos_existentes[nombre]}).")
                tipos_mapeados[nombre] = tipos_existentes[nombre]
            else:
                try:
                    nuevo_tipo = TipoAnalisis(nombre=nombre)
                    db.session.add(nuevo_tipo)
                    db.session.flush() # Para obtener el ID si es necesario inmediatamente
                    tipos_mapeados[nombre] = nuevo_tipo.id
                    tipos_existentes[nombre] = nuevo_tipo.id # Actualizar para el mapeo de herramientas
                    print(f"  Añadiendo Tipo '{nombre}' (ID: {nuevo_tipo.id})...")
                    tipos_added_count += 1
                except IntegrityError:
                    db.session.rollback()
                    log.error(f"Error de integridad al añadir Tipo '{nombre}'. ¿Ya existe?")
                except Exception as e:
                    db.session.rollback()
                    log.error(f"Error añadiendo Tipo '{nombre}': {e}")

        if tipos_added_count > 0:
            try:
                db.session.commit()
                print(f"Se añadieron {tipos_added_count} nuevos Tipos de Análisis.")
            except Exception as e:
                 db.session.rollback()
                 log.error(f"Error haciendo commit de Tipos de Análisis: {e}")
        else:
            print("No se añadieron nuevos Tipos de Análisis.")


        # --- Poblar HerramientaAnalisis ---
        herramientas_existentes = {h.nombre: h.id for h in HerramientaAnalisis.query.all()}
        herramientas_added_count = 0
        herramientas_updated_count = 0

        print("\n--- Poblando HerramientaAnalisis ---")
        for herr_data in HERRAMIENTAS:
            nombre_interno = herr_data["nombre"]
            tipo_nombre_ref = herr_data["tipo_nombre"]

            # Obtener el ID del TipoAnalisis correspondiente
            tipo_id = tipos_mapeados.get(tipo_nombre_ref)
            if tipo_id is None:
                log.warning(f"  Skipping herramienta '{nombre_interno}': Tipo de Análisis '{tipo_nombre_ref}' no encontrado.")
                continue

            # Crear/Actualizar herramienta
            herramienta_existente = HerramientaAnalisis.query.filter_by(nombre=nombre_interno).first()

            if herramienta_existente:
                # Actualizar campos si es necesario (ej. nombre_mostrado, descripcion, tipo_id)
                updated = False
                if herramienta_existente.nombre_mostrado != herr_data["nombre_mostrado"]:
                    herramienta_existente.nombre_mostrado = herr_data["nombre_mostrado"]
                    updated = True
                if herramienta_existente.lenguaje != herr_data["lenguaje"]:
                    herramienta_existente.lenguaje = herr_data["lenguaje"]
                    updated = True
                if herramienta_existente.tipo_analisis_id != tipo_id:
                    herramienta_existente.tipo_analisis_id = tipo_id
                    updated = True
                if herramienta_existente.descripcion != herr_data.get("descripcion"):
                     herramienta_existente.descripcion = herr_data.get("descripcion")
                     updated = True

                if updated:
                    print(f"  Actualizando herramienta '{nombre_interno}'...")
                    herramientas_updated_count += 1
                else:
                    print(f"  Herramienta '{nombre_interno}' ya existe y está actualizada.")

            else: # Si no existe, crearla
                 try:
                    nueva_herramienta = HerramientaAnalisis(
                        nombre=nombre_interno,
                        nombre_mostrado=herr_data["nombre_mostrado"],
                        lenguaje=herr_data["lenguaje"],
                        tipo_analisis_id=tipo_id,
                        descripcion=herr_data.get("descripcion")
                    )
                    db.session.add(nueva_herramienta)
                    print(f"  Añadiendo herramienta '{nombre_interno}'...")
                    herramientas_added_count += 1
                 except IntegrityError:
                     db.session.rollback()
                     log.error(f"Error de integridad al añadir Herramienta '{nombre_interno}'. ¿Ya existe?")
                 except Exception as e:
                     db.session.rollback()
                     log.error(f"Error añadiendo Herramienta '{nombre_interno}': {e}")

        # Commit final para herramientas
        if herramientas_added_count > 0 or herramientas_updated_count > 0:
            try:
                db.session.commit()
                if herramientas_added_count > 0: print(f"Se añadieron {herramientas_added_count} nuevas Herramientas de Análisis.")
                if herramientas_updated_count > 0: print(f"Se actualizaron {herramientas_updated_count} Herramientas de Análisis.")
            except Exception as e:
                 db.session.rollback()
                 log.error(f"Error haciendo commit de Herramientas de Análisis: {e}")
        else:
            print("No se añadieron ni actualizaron Herramientas de Análisis.")


    log.info("Proceso de seed finalizado.")

if __name__ == "__main__":
    seed_data()