# view_tables.py

import logging
from sqlalchemy import inspect, text
from flask import Flask # Importar Flask para crear instancia temporal
from flask.json import JSONEncoder
from datetime import datetime

# --- Importar SOLO Config, db (de extensions), y los modelos ---
from config import Config         # Importar la clase de configuración
from extensions import db        # Importar la INSTANCIA db (sin inicializar aquí)
try:
    from models import *         # Importar todos los modelos
except ImportError as e:
    print(f"Error importando modelos: {e}")
    print("Asegúrate de que 'models.py' exista y no tenga errores de importación.")
    exit(1)
# --- NO IMPORTAR 'app' desde 'app.py' ---

# ... (logger, ROW_LIMIT, VALUE_TRUNCATE_LIMIT, CustomJSONEncoder - sin cambios) ...
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)
ROW_LIMIT = 20
VALUE_TRUNCATE_LIMIT = 150

class CustomJSONEncoder(JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, datetime): return obj.isoformat()
            iterable = iter(obj)
        except TypeError: pass
        else: return list(iterable)
        return JSONEncoder.default(self, obj)

def display_table_contents():
    """Itera sobre los modelos registrados y muestra el contenido de sus tablas."""
    log.info("Iniciando inspección del contenido de las tablas...")

    # --- Crear una instancia TEMPORAL de Flask para este script ---
    script_app = Flask(__name__)
    script_app.config.from_object(Config) # Cargar la misma configuración
    # --- Inicializar la instancia db importada con la app temporal ---
    db.init_app(script_app)
    # ---------------------------------------------------------------

    # Usar el application context de la app temporal
    with script_app.app_context():
        # --- Imprimir URI de la Base de Datos ---
        try:
            db_uri = script_app.config.get('SQLALCHEMY_DATABASE_URI')
            if not db_uri:
                 print("\n--- ERROR: SQLALCHEMY_DATABASE_URI no encontrado en la configuración. ---")
                 return
            print(f"\n--- CONECTANDO A (desde script): {db_uri} ---")
            if db_uri.startswith('sqlite:///') and ':' not in db_uri[len('sqlite:///'):]:
                 path_part = db_uri[len('sqlite:///'):]
                 if ':' not in path_part:
                     print("--- ADVERTENCIA: Posible ruta relativa de SQLite. El script la resolverá desde donde se ejecute. ---")
            # ... (otras advertencias de URI) ...
        except Exception as e_cfg:
            print(f"\n--- ERROR OBTENIENDO CONFIG DB URI: {e_cfg} ---\n")
            return

        # --- Obtener Modelos Registrados (igual que antes, usa 'db') ---
        models_to_inspect = {}
        print("\n--- Buscando Modelos SQLAlchemy Registrados ---")
        try:
            mapper_registry = getattr(db.Model, 'registry', None)
            class_registry = getattr(mapper_registry, '_class_registry', None) if mapper_registry else None
            if not class_registry: class_registry = getattr(db.Model, '_decl_class_registry', {})

            if not class_registry:
                 log.error("Registro de modelos SQLAlchemy no encontrado o vacío.")
                 return

            found_any_model = False
            for name, cls in class_registry.items():
                 if isinstance(cls, type) and issubclass(cls, db.Model) and hasattr(cls, '__tablename__'):
                     if not name.startswith('_'):
                          table_name = cls.__tablename__
                          models_to_inspect[name] = cls
                          print(f"  [OK] Modelo Encontrado: {name} -> Tabla: {table_name}")
                          found_any_model = True
            if not found_any_model: print("  (No se encontraron modelos de usuario válidos)")
            print("----------------------------------------------")

        except Exception as e_reg:
             log.error(f"Error obteniendo registro de modelos: {e_reg}", exc_info=True)
             return

        if not models_to_inspect:
            log.warning("No se procesarán tablas ya que no se encontraron modelos válidos.")
            return

        log.info(f"Se inspeccionarán {len(models_to_inspect)} modelos/tablas.")

        # --- Iterar sobre Modelos y Mostrar Contenido (igual que antes) ---
        for model_name, model_class in sorted(models_to_inspect.items()):
            table_name = model_class.__tablename__
            print(f"\n\n{'='*10} Tabla: {table_name} (Modelo: {model_name}) {'='*10}")
            try:
                # 1. Contar filas
                row_count = -1
                try:
                    count_query = db.session.query(db.func.count(model_class.id))
                    row_count = count_query.scalar()
                    print(f"  >> Total filas (contadas): {row_count}")
                    if row_count == 0:
                        print("  >> Tabla está vacía.")
                        continue
                except Exception as e_count:
                     print(f"  !! Advertencia: No se pudo ejecutar count() para {table_name}: {e_count}")
                     print(f"  !! Intentando query.limit({ROW_LIMIT}).all() de todas formas...")

                # 2. Obtener filas
                print(f"  Querying primeras {ROW_LIMIT} filas...")
                rows = model_class.query.limit(ROW_LIMIT).all()
                print(f"  Query devolvió {len(rows)} filas.")

                if not rows:
                    if row_count != 0: print("  >> No se encontraron filas con query.limit().all(), aunque count() > 0.")
                    elif row_count == -1: print("  >> Tabla parece estar vacía.")
                    continue

                # 3. Mostrar detalles
                for i, row in enumerate(rows):
                    print(f"\n  --- Fila {i+1} ---")
                    # ... (código para iterar atributos/columnas e imprimir valores como antes) ...
                    mapper = inspect(model_class)
                    for attr in mapper.attrs:
                        col_name = attr.key
                        value_display = "<NO OBTENIDO>"
                        try:
                            value = getattr(row, col_name)
                            try:
                                value_json = json.dumps(value, cls=CustomJSONEncoder, ensure_ascii=False, indent=None)
                                if isinstance(value, str): value_display = value_json[1:-1]
                                elif isinstance(value, (bool, type(None))): value_display = value_json
                                elif isinstance(value, (int, float)): value_display = str(value)
                                else: value_display = value_json
                            except TypeError: value_display = repr(value)

                            if isinstance(value_display, str) and len(value_display) > VALUE_TRUNCATE_LIMIT:
                                value_display = value_display[:VALUE_TRUNCATE_LIMIT] + '...'
                        except Exception as e_attr: value_display = f"<ERROR: {e_attr}>"
                        print(f"    {col_name}: {value_display}")


                if row_count > ROW_LIMIT: print(f"\n  ... ({row_count - ROW_LIMIT} filas omitidas)")
                elif len(rows) == ROW_LIMIT and row_count == -1: print(f"\n  ... (Podrían existir más filas)")

            except Exception as e_query:
                log.error(f"  !! Error GENERAL al consultar tabla {table_name}: {e_query}", exc_info=True)

        log.info("Inspección de tablas completada.")

if __name__ == "__main__":
    display_table_contents()