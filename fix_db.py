# Crea un archivo fix_db.py

import sqlite3

# Ajusta la ruta a tu base de datos
conn = sqlite3.connect('app.db')
cursor = conn.cursor()

# Verificar las columnas existentes
cursor.execute("PRAGMA table_info(resultado_de_evaluacion)")
columnas = [col[1] for col in cursor.fetchall()]
print("Columnas actuales:", columnas)

# Añadir las columnas faltantes si no existen
columnas_a_agregar = [
    "salida_obtenida_repr TEXT",
    "salida_esperada_repr TEXT",
    "entrada_repr TEXT",
    "argumentos_repr TEXT",
    "stderr_obtenido TEXT",
    "stderr_obtenido_repr TEXT",
    "tiempo_ejecucion_ms INTEGER",
    "memoria_utilizada_kb INTEGER",
    "estado_ejecucion VARCHAR(50)",
    "codigo_retorno INTEGER",
    "diferencias_resumen TEXT",
    "fecha_ejecucion DATETIME"
]

for col_def in columnas_a_agregar:
    col_name = col_def.split()[0]
    if col_name not in columnas:
        print(f"Añadiendo columna: {col_name}")
        try:
            cursor.execute(f"ALTER TABLE resultado_de_evaluacion ADD COLUMN {col_def}")
        except sqlite3.OperationalError as e:
            print(f"Error al añadir {col_name}: {e}")

conn.commit()
conn.close()
print("¡Proceso completado!")