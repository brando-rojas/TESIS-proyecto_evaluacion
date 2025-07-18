# configure_teachers.py

import logging
from sqlalchemy.exc import IntegrityError

# --- Importar componentes de la app ---
try:
    from app import app, db
    from models import Usuario, Curso, CicloAcademico, OfertaDeCurso, Horario
except ImportError as e:
    print(f"Error crítico al importar componentes: {e}")
    exit(1)

# --- CONFIGURACIÓN BASADA EN TU JSON ---

# 1. Estructura académica existente o a crear
TARGET_CURSO = {"codigo": "1INF01", "nombre": "Fundamentos de Programacion"}
TARGET_CICLO = {"nombre": "2024-2"}
TARGET_HORARIO = {"nombre": "H0682"}

# 2. Datos de los docentes a configurar
DOCENTES_A_CONFIGURAR = [
    {
        'nombre': 'Luis Vives Garnique',
        'email': 'luis.vives@pucp.edu.pe',
        'password': 'profesor.tesis.2024'
    },
    {
        'nombre': 'Victor Gómez Razza',
        'email': 'vhgomezr@pucp.edu.pe',
        'password': 'profesor.tesis.2024'
    }
]

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)


def configure_existing_environment():
    """
    Script para añadir y configurar docentes en un entorno académico existente.
    1. Busca o crea el Curso, Ciclo y Horario específicos.
    2. Crea las cuentas de los docentes si no existen.
    3. Asocia los docentes al Horario específico.
    """
    log.info("Iniciando configuración de docentes en el entorno existente...")

    with app.app_context():
        try:
            # --- PASO 1: Asegurar que la estructura académica del JSON exista ---
            log.info(f"--- Verificando estructura para Curso '{TARGET_CURSO['nombre']}' y Ciclo '{TARGET_CICLO['nombre']}' ---")

            ciclo = CicloAcademico.query.filter_by(nombre=TARGET_CICLO['nombre']).first()
            if not ciclo:
                ciclo = CicloAcademico(nombre=TARGET_CICLO['nombre'])
                db.session.add(ciclo); db.session.commit()
                log.info(f"Ciclo '{ciclo.nombre}' no existía y fue creado.")
            else:
                log.info(f"Ciclo '{ciclo.nombre}' encontrado.")

            curso = Curso.query.filter_by(codigo=TARGET_CURSO['codigo']).first()
            if not curso:
                curso = Curso(codigo=TARGET_CURSO['codigo'], nombre=TARGET_CURSO['nombre'])
                db.session.add(curso); db.session.commit()
                log.info(f"Curso '{curso.nombre}' no existía y fue creado.")
            else:
                log.info(f"Curso '{curso.nombre}' encontrado.")

            oferta = OfertaDeCurso.query.filter_by(curso_id=curso.id, ciclo_academico_id=ciclo.id).first()
            if not oferta:
                oferta = OfertaDeCurso(curso_id=curso.id, ciclo_academico_id=ciclo.id)
                db.session.add(oferta); db.session.commit()
                log.info("Oferta de curso no existía y fue creada.")
            else:
                log.info("Oferta de curso encontrada.")

            horario = Horario.query.filter_by(nombre=TARGET_HORARIO['nombre'], oferta_de_curso_id=oferta.id).first()
            if not horario:
                horario = Horario(nombre=TARGET_HORARIO['nombre'], oferta_de_curso_id=oferta.id)
                db.session.add(horario); db.session.commit()
                log.info(f"Horario '{horario.nombre}' no existía y fue creado.")
            else:
                log.info(f"Horario '{horario.nombre}' encontrado.")

            # --- PASO 2: Crear o encontrar los usuarios docentes ---
            log.info("\n--- Verificando y creando cuentas de docentes ---")
            
            docentes_a_asociar = []
            for docente_data in DOCENTES_A_CONFIGURAR:
                docente = Usuario.query.filter_by(email=docente_data['email']).first()
                if not docente:
                    log.info(f"Creando usuario para {docente_data['nombre']}...")
                    docente = Usuario(
                        nombre=docente_data['nombre'],
                        email=docente_data['email'],
                        rol='docente'
                    )
                    docente.set_password(docente_data['password'])
                    db.session.add(docente)
                    # Hacemos commit aquí para que el objeto tenga un ID y pueda ser asociado
                    db.session.commit()
                else:
                    log.info(f"Usuario {docente.nombre} ya existe.")
                
                docentes_a_asociar.append(docente)

            # --- PASO 3: Asociar los docentes al horario específico ---
            log.info(f"\n--- Asociando docentes al horario '{horario.nombre}' del curso '{curso.nombre}' ---")
            
            for docente in docentes_a_asociar:
                if docente not in horario.usuarios:
                    horario.usuarios.append(docente)
                    log.info(f"Asociando a {docente.nombre}...")
                else:
                    log.info(f"{docente.nombre} ya está asociado a este horario.")
            
            # Guardar las nuevas asociaciones en la tabla 'usuario_horario'
            db.session.commit()

            log.info("\n¡Configuración de docentes completada exitosamente!")
            print("\nResumen de la configuración:")
            print(f"  - Curso: '{curso.nombre}'")
            print(f"  - Horario: '{horario.nombre}'")
            print(f"  - Los siguientes docentes ahora tienen acceso a este horario:")
            for d in DOCENTES_A_CONFIGURAR:
                print(f"    - {d['nombre']} ({d['email']}) | Contraseña: {d['password']}")
        
        except Exception as e:
            log.error(f"Ocurrió un error grave durante la configuración: {e}")
            db.session.rollback()
            log.info("Se han revertido todos los cambios debido al error.")


if __name__ == "__main__":
    configure_existing_environment()