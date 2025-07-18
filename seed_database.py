import logging
from app import app, db
from models import Usuario, Curso, CicloAcademico, OfertaDeCurso, Horario

# --- CONFIGURACIÓN CENTRAL DE DATOS ---

# 1. Define la estructura académica que quieres asegurar que exista
ESTRUCTURA_ACADEMICA = {
    "curso": {"codigo": "1INF01", "nombre": "Fundamentos de Programación"},
    "ciclo": {"nombre": "2024-2"},
    "horario": {"nombre": "H0682"}
}

# 2. Define los usuarios a crear o actualizar
USUARIOS_A_CONFIGURAR = [
    # --- DOCENTES ---
    {
        'rol': 'docente',
        'nombre': 'Luis Vives Garnique',
        'email': 'luis.vives@pucp.edu.pe',
        'password': 'profesor.tesis.2024',
        'codigo': None # Los docentes no tienen código
    },
    {
        'rol': 'docente',
        'nombre': 'Victor Gómez Razza',
        'email': 'vhgomezr@pucp.edu.pe',
        'password': 'profesor.tesis.2024',
        'codigo': None
    },
    {
        'rol': 'docente',
        'nombre': 'Johan Baldeón Medrano',
        'email': 'johan.baldeon@pucp.edu.pe',
        'password': 'profesor.tesis.2024',
        'codigo': None
    },
    {
        'rol': 'docente',
        'nombre': 'Luis Muroya Tokushima',
        'email': 'luis.muroya@pucp.edu.pe',
        'password': 'profesor.tesis.2024',
        'codigo': None
    },
    # --- ALUMNOS ---
    {
        'rol': 'alumno',
        'nombre': 'Ana Estudiante',
        'email': 'ana@ejemplo.com',
        'password': 'password123',
        'codigo': '20201111'
    },
    {
        'rol': 'alumno',
        'nombre': 'Juan Estudiante',
        'email': 'juan@ejemplo.com',
        'password': 'password123',
        'codigo': '20202222'
    },
    {
        'rol': 'alumno',
        'nombre': 'Pedro Estudiante',
        'email': 'pedro@ejemplo.com',
        'password': 'nueva_clave_segura', # Se actualizará a esta
        'codigo': '20191251' # Si ya lo tiene, no se cambia. Si no, se añade.
    }
]

# --- SCRIPT DE CONFIGURACIÓN ---

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

def seed_database():
    """
    Script para crear o actualizar la base de datos con una configuración inicial
    de cursos, horarios, docentes y alumnos.
    """
    log.info("Iniciando siembra de datos en la base de datos...")

    with app.app_context():
        try:
            # --- PASO 1: Asegurar que la estructura académica exista ---
            target_curso = ESTRUCTURA_ACADEMICA["curso"]
            target_ciclo = ESTRUCTURA_ACADEMICA["ciclo"]
            target_horario = ESTRUCTURA_ACADEMICA["horario"]

            ciclo = CicloAcademico.query.filter_by(nombre=target_ciclo['nombre']).first()
            if not ciclo:
                ciclo = CicloAcademico(nombre=target_ciclo['nombre'])
                db.session.add(ciclo)
                log.info(f"Creado ciclo: '{ciclo.nombre}'")

            curso = Curso.query.filter_by(codigo=target_curso['codigo']).first()
            if not curso:
                curso = Curso(**target_curso)
                db.session.add(curso)
                log.info(f"Creado curso: '{curso.nombre}'")

            db.session.commit() # Commit para asegurar que ciclo y curso tengan IDs

            oferta = OfertaDeCurso.query.filter_by(curso_id=curso.id, ciclo_academico_id=ciclo.id).first()
            if not oferta:
                oferta = OfertaDeCurso(curso_id=curso.id, ciclo_academico_id=ciclo.id)
                db.session.add(oferta)
                log.info(f"Creada oferta para el curso '{curso.nombre}' en el ciclo '{ciclo.nombre}'")
            
            db.session.commit() # Commit para asegurar que oferta tenga ID

            horario = Horario.query.filter_by(nombre=target_horario['nombre'], oferta_de_curso_id=oferta.id).first()
            if not horario:
                horario = Horario(nombre=target_horario['nombre'], oferta_de_curso_id=oferta.id)
                db.session.add(horario)
                log.info(f"Creado horario: '{horario.nombre}'")

            # --- PASO 2: Crear o actualizar los usuarios ---
            log.info("\n--- Procesando usuarios ---")
            
            usuarios_procesados = []
            for user_data in USUARIOS_A_CONFIGURAR:
                usuario = Usuario.query.filter_by(email=user_data['email']).first()
                
                if usuario:
                    # El usuario ya existe, lo actualizamos
                    log.info(f"Actualizando usuario existente: {usuario.email}")
                    usuario.set_password(user_data['password']) # Actualizar contraseña
                    if usuario.rol == 'alumno' and not usuario.codigo and user_data['codigo']:
                        usuario.codigo = user_data['codigo'] # Añadir código si no lo tiene
                        log.info(f"  -> Añadido código '{usuario.codigo}'")
                else:
                    # El usuario no existe, lo creamos
                    log.info(f"Creando nuevo usuario: {user_data['email']}")
                    usuario = Usuario(
                        nombre=user_data['nombre'],
                        email=user_data['email'],
                        rol=user_data['rol'],
                        codigo=user_data['codigo'] if user_data['rol'] == 'alumno' else None
                    )
                    usuario.set_password(user_data['password'])
                    db.session.add(usuario)
                
                usuarios_procesados.append(usuario)
            
            db.session.commit() # Guardar todos los usuarios creados o actualizados

            # --- PASO 3: Asociar todos los usuarios al horario ---
            log.info(f"\n--- Asociando usuarios al horario '{horario.nombre}' ---")
            
            for usuario in usuarios_procesados:
                if usuario not in horario.usuarios:
                    horario.usuarios.append(usuario)
                    log.info(f"Asociando a {usuario.nombre}...")
                else:
                    log.info(f"{usuario.nombre} ya está asociado.")
            
            db.session.commit()

            log.info("\n¡Configuración completada exitosamente!")
            print("\nResumen de la configuración aplicada:")
            print(f"  - Curso: '{curso.nombre}' | Horario: '{horario.nombre}'")
            print(f"  - Los siguientes usuarios existen y están asociados:")
            for u in USUARIOS_A_CONFIGURAR:
                print(f"    - {u['rol'].capitalize()}: {u['nombre']} ({u['email']}) | Pass: '{u['password']}'")

        except Exception as e:
            log.error(f"Ocurrió un error grave durante la siembra de datos: {e}", exc_info=True)
            db.session.rollback()
            log.info("Se han revertido todos los cambios debido al error.")

if __name__ == "__main__":
    seed_database()