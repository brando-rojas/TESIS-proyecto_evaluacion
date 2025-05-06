# routes.py

from app import app
from flask import render_template, redirect, url_for, flash, request, make_response
from models import db, Usuario, Examen, Pregunta, Entrega, Evaluacion, CasoDePrueba, Horario, OfertaDeCurso, Curso, usuario_horario
from models import *
from flask_login import login_user, logout_user, login_required, current_user
from forms import LoginForm, RegistroForm, CrearExamenForm, EditarExamenForm, PreguntaForm, EntregaForm, DeleteForm, CasoDePruebaForm, LENGUAJES_SOPORTADOS
from evaluator import evaluar_entrega
from datetime import datetime
import sys
import json
import os
from werkzeug.utils import secure_filename

# Define una carpeta para almacenar las subidas
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Agregar después de las otras funciones auxiliares
def obtener_entregas_recientes(docente_id, limite=5):
    """
    Obtiene las entregas más recientes relacionadas con los cursos del docente.
    """
    # Obtener horarios del docente
    horarios = Usuario.query.get(docente_id).horarios
    
    # Obtener ids de exámenes asociados a esos horarios
    examenes_ids = db.session.query(Examen.id).filter(
        Examen.horario_id.in_([h.id for h in horarios])
    ).all()
    examenes_ids = [id[0] for id in examenes_ids]
    
    # Obtener las entregas más recientes para esos exámenes
    entregas_recientes = Entrega.query.join(Pregunta).filter(
        Pregunta.examen_id.in_(examenes_ids)
    ).order_by(Entrega.fecha_entrega.desc()).limit(limite).all()
    
    return entregas_recientes

# Agregar al principio del archivo routes.py o crear un archivo helpers.py
from sqlalchemy import func
from collections import defaultdict

def obtener_evaluaciones_por_examen(examen_id=None, curso_id=None):
    """
    Obtiene las evaluaciones filtradas por examen y/o curso.
    Sólo incluye la última entrega de cada alumno para cada pregunta.
    """
    # Base query - join todas las tablas necesarias
    query = db.session.query(Evaluacion)\
        .join(Entrega, Evaluacion.entrega_id == Entrega.id)\
        .join(Pregunta, Entrega.pregunta_id == Pregunta.id)\
        .join(Examen, Pregunta.examen_id == Examen.id)\
        .join(Horario, Examen.horario_id == Horario.id)\
        .join(OfertaDeCurso, Horario.oferta_de_curso_id == OfertaDeCurso.id)\
        .join(Curso, OfertaDeCurso.curso_id == Curso.id)
    
    # Aplicar filtros si se proporcionan
    if examen_id:
        query = query.filter(Examen.id == examen_id)
    if curso_id:
        query = query.filter(Curso.id == curso_id)
    
    # Obtener todas las entregas que coinciden con los filtros
    evaluaciones = query.all()
    
    # Diccionario para rastrear la última entrega de cada alumno por pregunta
    ultimas_entregas = {}
    
    for eval in evaluaciones:
        alumno_id = eval.entrega.alumno_id
        pregunta_id = eval.entrega.pregunta_id
        fecha_entrega = eval.entrega.fecha_entrega
        
        key = (alumno_id, pregunta_id)
        
        # Si no existe esta combinación alumno-pregunta o si esta entrega es más reciente
        if key not in ultimas_entregas or fecha_entrega > ultimas_entregas[key][1]:
            ultimas_entregas[key] = (eval.id, fecha_entrega)
    
    # Obtener solo los IDs de las evaluaciones que corresponden a las últimas entregas
    ids_ultimas_evaluaciones = [eval_id for eval_id, _ in ultimas_entregas.values()]
    
    # Filtrar las evaluaciones originales para quedarnos solo con las últimas
    return [eval for eval in evaluaciones if eval.id in ids_ultimas_evaluaciones]

def calcular_estadisticas_evaluaciones(evaluaciones):
    """
    Calcula estadísticas generales a partir de una lista de evaluaciones.
    """
    if not evaluaciones:
        return {
            'total_evaluaciones': 0,
            'promedio_general': 0,
            'estudiantes_unicos': 0,
            'examenes_unicos': 0,
            'distribuciones': [0, 0, 0, 0, 0],  # 0-20%, 21-40%, 41-60%, 61-80%, 81-100%
            'rendimiento_examenes': {}
        }
    
    # Conjunto para rastrear IDs únicos
    estudiantes_ids = set()
    examenes_ids = set()
    
    # Para calcular promedios por examen
    examen_stats = defaultdict(lambda: {'total_puntos': 0, 'max_puntos': 0, 'count': 0})
    
    # Para distribución de calificaciones
    distribuciones = [0, 0, 0, 0, 0]  # 0-20%, 21-40%, 41-60%, 61-80%, 81-100%
    
    # Variables para promedio general
    total_puntos = 0
    total_max_puntos = 0
    
    # Analizar cada evaluación
    for eval in evaluaciones:
        estudiantes_ids.add(eval.entrega.alumno_id)
        examen_id = eval.entrega.pregunta.examen_id
        examenes_ids.add(examen_id)
        
        puntos = eval.puntaje_obtenido
        max_puntos = eval.entrega.pregunta.puntaje_total
        
        # Sumar para el promedio general
        total_puntos += puntos
        total_max_puntos += max_puntos
        
        # Agregar a las estadísticas por examen
        examen_titulo = eval.entrega.pregunta.examen.titulo
        examen_stats[examen_titulo]['total_puntos'] += puntos
        examen_stats[examen_titulo]['max_puntos'] += max_puntos
        examen_stats[examen_titulo]['count'] += 1
        
        # Calcular porcentaje y actualizar distribución
        if max_puntos > 0:
            porcentaje = (puntos / max_puntos) * 100
            if porcentaje <= 20:
                distribuciones[0] += 1
            elif porcentaje <= 40:
                distribuciones[1] += 1
            elif porcentaje <= 60:
                distribuciones[2] += 1
            elif porcentaje <= 80:
                distribuciones[3] += 1
            else:
                distribuciones[4] += 1
    
    # Calcular el promedio general
    promedio_general = 0
    if total_max_puntos > 0:
        promedio_general = (total_puntos / total_max_puntos) * 100
    
    # Calcular promedios por examen
    rendimiento_examenes = {}
    for examen, stats in examen_stats.items():
        if stats['max_puntos'] > 0:
            rendimiento_examenes[examen] = (stats['total_puntos'] / stats['max_puntos']) * 100
        else:
            rendimiento_examenes[examen] = 0
    
    return {
        'total_evaluaciones': len(evaluaciones),
        'promedio_general': round(promedio_general, 1),
        'estudiantes_unicos': len(estudiantes_ids),
        'examenes_unicos': len(examenes_ids),
        'distribuciones': distribuciones,
        'rendimiento_examenes': rendimiento_examenes
    }

def obtener_cursos_y_examenes_docente(docente_id):
    """
    Obtiene la lista de cursos y exámenes disponibles para un docente específico.
    """
    # Obtener horarios del docente
    horarios = Usuario.query.get(docente_id).horarios
    
    # Obtener cursos únicos
    cursos = {}
    for horario in horarios:
        curso = horario.oferta_de_curso.curso
        if curso.id not in cursos:
            cursos[curso.id] = {
                'id': curso.id,
                'nombre': curso.nombre,
                'codigo': curso.codigo
            }
    
    # Obtener exámenes asociados a los horarios del docente
    examenes = []
    for horario in horarios:
        for examen in horario.examenes:
            examenes.append({
                'id': examen.id,
                'titulo': examen.titulo,
                'curso_id': horario.oferta_de_curso.curso_id,
                'curso_nombre': horario.oferta_de_curso.curso.nombre
            })
    
    return list(cursos.values()), examenes

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Si el usuario ya está autenticado Y 
    # está intentando enviar el formulario de login de nuevo (POST)
    if current_user.is_authenticated and request.method == 'POST':
        logout_user()
        print("Usuario autenticado, cerrando sesión...")
    # Si ya está autenticado y es una petición GET, 
    # redirigir al dashboard (comportamiento actual)
    elif current_user.is_authenticated and request.method == 'GET':
        response = make_response(redirect(url_for('dashboard')))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        return response

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.contraseña.data
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and usuario.check_password(password):
            login_user(usuario)
            flash('Has iniciado sesión correctamente.', 'success')
            response = make_response(redirect(url_for('dashboard'))) # O next_page
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '-1'
            return response
        else:
            flash('Correo o contraseña incorrectos.', 'danger')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistroForm()
    if form.validate_on_submit():
        nombre = form.nombre.data
        email = form.email.data
        contraseña = form.contraseña.data
        rol = form.rol.data

        # Verificar si el email ya existe
        existing_user = Usuario.query.filter_by(email=email).first()
        if existing_user:
            flash('El correo electrónico ya está registrado.', 'warning')
            return redirect(url_for('register'))

        nuevo_usuario = Usuario(
            nombre=nombre,
            email=email,
            rol=rol
        )
        nuevo_usuario.set_password(contraseña)
        db.session.add(nuevo_usuario)
        db.session.commit()

        flash('Te has registrado exitosamente. Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión exitosamente.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import datetime
    now = datetime.utcnow()  # Para comparar con fechas de exámenes
    
    if current_user.rol == 'alumno':
        horarios = current_user.horarios
        examenes = Examen.query.filter(Examen.horario_id.in_([h.id for h in horarios])).all()
        
        # Obtener entregas recientes para el alumno
        entregas_recientes = Entrega.query.filter(
            Entrega.alumno_id == current_user.id
        ).order_by(Entrega.fecha_entrega.desc()).limit(5).all()

        # No se cuenta entregas cuyo examen sea None
        entregas_recientes = [entrega for entrega in entregas_recientes if entrega.pregunta is not None]
        
        return render_template(
            'dashboard_alumno.html', 
            examenes=examenes, 
            now=now,
            entregas_recientes=entregas_recientes
        )
    elif current_user.rol == 'docente':
        horarios = current_user.horarios
        examenes = Examen.query.filter(Examen.horario_id.in_([h.id for h in horarios])).all()
        return render_template(
            'dashboard_docente.html', 
            examenes=examenes, 
            now=now, 
            obtener_entregas_recientes=obtener_entregas_recientes
        )
    else:
        flash('Rol de usuario desconocido.', 'danger')
        return redirect(url_for('logout'))

@app.route('/examen/<int:examen_id>')
@login_required
def ver_examen(examen_id):
    from datetime import datetime  # asegúrate de que datetime esté importado
    
    examen = Examen.query.get_or_404(examen_id)
    if examen.horario not in current_user.horarios:
        flash('No tienes acceso a este examen.', 'danger')
        return redirect(url_for('dashboard'))
    
    if current_user.rol == 'docente':
        form = DeleteForm()
        return render_template('ver_examen.html', examen=examen, form=form, now=datetime.utcnow())
    elif current_user.rol == 'alumno':
        return render_template('ver_examen_alumno.html', examen=examen, now=datetime.utcnow())  # <-- añadir now=datetime.utcnow()
    else:
        flash('Rol de usuario desconocido.', 'danger')
        return redirect(url_for('logout'))

@app.route('/pregunta/<int:pregunta_id>', methods=['GET', 'POST'])
@login_required
def responder_pregunta(pregunta_id):
    pregunta = Pregunta.query.get_or_404(pregunta_id)
    if pregunta.examen.horario not in current_user.horarios:
        flash('No tienes acceso a esta pregunta.', 'danger')
        return redirect(url_for('dashboard'))
    
    form = EntregaForm()
    if form.validate_on_submit():
        codigo_fuente = form.codigo_fuente.data
        archivo = form.archivo.data
        # Manejar la subida del archivo si existe
        nombre_archivo = None
        if archivo:
            nombre_archivo = secure_filename(archivo.filename)
            archivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo))
        
        entrega = Entrega(
            fecha_entrega=datetime.utcnow(),
            codigo_fuente=codigo_fuente,
            archivo=nombre_archivo,  # Campo para el nombre del archivo
            alumno_id=current_user.id,
            pregunta_id=pregunta.id
        )
        db.session.add(entrega)
        db.session.commit()
        
        # Evaluar la entrega
        evaluar_entrega(entrega)
        
        flash('Tu entrega ha sido evaluada.', 'success')
        return redirect(url_for('ver_resultado', entrega_id=entrega.id))
    
    return render_template('responder_pregunta.html', pregunta=pregunta, form=form)

@app.route('/resultado/<int:entrega_id>')
@login_required
def ver_resultado(entrega_id):
    entrega = Entrega.query.get_or_404(entrega_id)
    if entrega.alumno_id != current_user.id:
        flash('No tienes permiso para ver este resultado.', 'danger')
        return redirect(url_for('dashboard'))

    evaluacion = entrega.evaluacion
    if not evaluacion:
        flash('La entrega aún no ha sido evaluada.', 'warning')
        return redirect(url_for('dashboard'))

    return render_template('ver_resultado.html', evaluacion=evaluacion)

@app.route('/docente/gestionar_examenes')
@login_required
def gestionar_examenes():
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))

    horarios = current_user.horarios
    examenes = Examen.query.filter(Examen.horario_id.in_([h.id for h in horarios])).all()
    form = DeleteForm()  # Instanciar el formulario de eliminación
    return render_template('gestionar_examenes.html', examenes=examenes, form=form)

@app.route('/docente/crear_examen', methods=['GET', 'POST'])
@login_required
def crear_examen():
    """Ruta para crear un nuevo examen con preguntas y configuración."""
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))

    form = CrearExamenForm()

    # Poblar choices de cursos para el formulario
    try:
        cursos = Curso.query.join(OfertaDeCurso).join(Horario).join(usuario_horario).filter(
            usuario_horario.c.usuario_id == current_user.id
        ).distinct().order_by(Curso.nombre).all()
        form.cursos.choices = [(c.id, f"{c.codigo} - {c.nombre}") for c in cursos]
    except Exception as e:
        flash('Error al cargar los cursos.', 'danger')
        print(f"Error cargando cursos: {e}", file=sys.stderr)
        form.cursos.choices = []

    if request.method == 'POST':
        print("Procesando POST /docente/crear_examen - Poblando Choices Linter")
        for i, pregunta_subform in enumerate(form.preguntas):
            try:
                lenguaje_seleccionado = request.form.get(f'preguntas-{i}-lenguaje_programacion')
                print(f"  Poblando choices pregunta {i}, lenguaje: {lenguaje_seleccionado}")
                if lenguaje_seleccionado:
                    # --- INICIO: Lógica de obtener_linters_para_lenguaje_bd integrada ---
                    opciones = [('', '--- Ninguno ---')]
                    herramientas = HerramientaAnalisis.query.filter_by(
                        lenguaje=lenguaje_seleccionado
                    ).order_by(HerramientaAnalisis.nombre_mostrado).all()
                    opciones.extend([(h.nombre, h.nombre_mostrado) for h in herramientas])
                    pregunta_subform.linter_perfil.choices = opciones
                    # --- FIN: Lógica integrada ---
                else:
                    pregunta_subform.linter_perfil.choices = [('', '--- Ninguno ---')]
            except Exception as e_choices:
                 print(f"Error poblando choices pregunta {i}: {e_choices}", file=sys.stderr)
                 pregunta_subform.linter_perfil.choices = [('', '--- Error ---')]

    if form.validate_on_submit():
        # --- Procesamiento POST ---
        try:
            titulo = form.titulo.data
            descripcion = form.descripcion.data
            fecha_cierre = form.fecha_cierre.data
            selected_curso_ids = form.cursos.data

            # Flags globales
            habilitar_formato_global = form.habilitar_formato.data
            habilitar_metricas = form.habilitar_metricas.data
            habilitar_similitud = form.habilitar_similitud.data
            habilitar_rendimiento = form.habilitar_rendimiento.data # Nombre correcto

            horarios = Horario.query.join(OfertaDeCurso).filter(
                OfertaDeCurso.curso_id.in_(selected_curso_ids)
            ).all()

            if not horarios:
                flash('No hay horarios válidos asociados a los cursos seleccionados.', 'warning')
                # Renderizar de nuevo con el error y los datos ingresados
                # Necesitamos volver a cargar los linters para el renderizado
                todos_los_linters = {}
                try:
                    codigos_lenguaje = [lang[0] for lang in LENGUAJES_SOPORTADOS]
                    for lenguaje_codigo in codigos_lenguaje:
                        opciones = [('', '--- Ninguno ---')]
                        herramientas = HerramientaAnalisis.query.filter_by(lenguaje=lenguaje_codigo).order_by(HerramientaAnalisis.nombre_mostrado).all()
                        opciones.extend([(h.nombre, h.nombre_mostrado) for h in herramientas])
                        todos_los_linters[lenguaje_codigo] = opciones
                except Exception as e_linter:
                    print(f"Error obteniendo linters (POST error): {e_linter}", file=sys.stderr)
                    for lc in [lang[0] for lang in LENGUAJES_SOPORTADOS]: todos_los_linters[lc] = [('', '--- Error ---')]

                return render_template('crear_examen.html', form=form, editar=False, todos_los_linters_json=json.dumps(todos_los_linters))


            # Usar transacción para asegurar atomicidad
            with db.session.begin_nested():
                for horario in horarios:
                    print(f"Creando examen para horario ID: {horario.id}")
                    nuevo_examen = Examen(
                        titulo=titulo,
                        descripcion=descripcion,
                        fecha_publicacion=datetime.utcnow(),
                        fecha_cierre=fecha_cierre,
                        horario_id=horario.id
                    )
                    db.session.add(nuevo_examen)
                    db.session.flush() # Obtener ID del examen

                    config_analisis = ConfiguracionExamen(
                        examen_id=nuevo_examen.id,
                        habilitar_formato=habilitar_formato_global,
                        habilitar_metricas=habilitar_metricas,
                        habilitar_similitud=habilitar_similitud,
                        habilitar_rendimiento=habilitar_rendimiento # Nombre correcto
                    )
                    db.session.add(config_analisis)

                    # Procesar preguntas añadidas dinámicamente
                    for i, pregunta_form_data in enumerate(form.preguntas.data): # Iterar sobre la data
                        print(f"  Procesando pregunta índice {i}: {pregunta_form_data.get('enunciado', '')[:30]}...")
                        # Crear JSON de configuración de formato
                        config_formato = None
                        perfil_linter = pregunta_form_data.get('linter_perfil')
                        args_adicionales = pregunta_form_data.get('linter_args_adicionales', '')

                        if habilitar_formato_global and perfil_linter:
                            config_formato = {
                                "perfil": perfil_linter,
                                "args_adicionales": args_adicionales or ""
                            }
                        config_formato_json = json.dumps(config_formato) if config_formato else None
                        print(f"    Config formato JSON: {config_formato_json}")

                        nueva_pregunta = Pregunta(
                            enunciado=pregunta_form_data['enunciado'],
                            puntaje_total=pregunta_form_data['puntaje_total'],
                            lenguaje_programacion=pregunta_form_data['lenguaje_programacion'],
                            rubrica_evaluacion=pregunta_form_data.get('rubrica_evaluacion') or None,
                            configuracion_formato_json=config_formato_json,
                            examen_id=nuevo_examen.id
                        )
                        db.session.add(nueva_pregunta)
                        db.session.flush() # Obtener ID de la pregunta

                        # Procesar casos de prueba anidados
                        for j, caso_data in enumerate(pregunta_form_data.get('casos_de_prueba', [])):
                            print(f"    Procesando caso índice {j} para pregunta {nueva_pregunta.id}")
                            nuevo_caso = CasoDePrueba(
                                descripcion=caso_data.get('descripcion'), # Usar get para opcionales
                                argumentos=caso_data.get('argumentos'),
                                entrada=caso_data.get('entrada'),
                                salida_esperada=caso_data.get('salida_esperada'),
                                puntos=caso_data['puntos'], # Asumir requerido
                                es_oculto=caso_data.get('es_oculto', False),
                                pregunta_id=nueva_pregunta.id
                            )
                            db.session.add(nuevo_caso)

            # Commit de la transacción principal si todo fue bien
            db.session.commit()
            flash(f'Examen "{titulo}" creado exitosamente para {len(horarios)} horario(s).', 'success')
            return redirect(url_for('gestionar_examenes'))

        except Exception as e:
            db.session.rollback() # Rollback en caso de error
            flash('Ocurrió un error grave al crear los exámenes. Inténtalo nuevamente.', 'danger')
            print(f"Error al crear exámenes: {e}", file=sys.stderr)
            # Volver a renderizar el formulario con los datos ingresados y errores
            # Necesitamos obtener los linters de nuevo para el renderizado
            todos_los_linters = {}
            try:
                codigos_lenguaje = [lang[0] for lang in LENGUAJES_SOPORTADOS]
                for lenguaje_codigo in codigos_lenguaje:
                    opciones = [('', '--- Ninguno ---')]
                    herramientas = HerramientaAnalisis.query.filter_by(lenguaje=lenguaje_codigo).order_by(HerramientaAnalisis.nombre_mostrado).all()
                    opciones.extend([(h.nombre, h.nombre_mostrado) for h in herramientas])
                    todos_los_linters[lenguaje_codigo] = opciones
            except Exception as e_linter:
                print(f"Error obteniendo linters (POST error): {e_linter}", file=sys.stderr)
                for lc in [lang[0] for lang in LENGUAJES_SOPORTADOS]: todos_los_linters[lc] = [('', '--- Error ---')]

            return render_template('crear_examen.html', form=form, editar=False, todos_los_linters_json=json.dumps(todos_los_linters))

    # --- Método GET: Obtener TODOS los linters y pasarlos ---
    print("Procesando GET para /docente/crear_examen")
    todos_los_linters = {}
    try:
        codigos_lenguaje = [lang[0] for lang in LENGUAJES_SOPORTADOS]
        for lenguaje_codigo in codigos_lenguaje:
            opciones = [('', '--- Ninguno ---')]
            herramientas = HerramientaAnalisis.query.filter_by(
                lenguaje=lenguaje_codigo
            ).order_by(HerramientaAnalisis.nombre_mostrado).all()
            opciones.extend([(h.nombre, h.nombre_mostrado) for h in herramientas])
            todos_los_linters[lenguaje_codigo] = opciones
        print("--- DEBUG: Datos para Template ---")
        print(f"Todos Linters Dict: {todos_los_linters}") # Verifica el diccionario Python
        todos_los_linters_json_str = json.dumps(todos_los_linters)
        print(f"Todos Linters JSON: {todos_los_linters_json_str}") # Verifica la cadena JSON
        print("---------------------------------")
        print(f"Linters obtenidos para GET: {len(todos_los_linters)} lenguajes")
    except Exception as e:
        flash('Error al cargar opciones de linter.', 'warning')
        print(f"Error obteniendo linters para el formulario GET: {e}", file=sys.stderr)
        for lc in [lang[0] for lang in LENGUAJES_SOPORTADOS]: todos_los_linters[lc] = [('', '--- Error ---')]

    return render_template(
        'crear_examen.html',
        form=form,
        editar=False,
        todos_los_linters_json=json.dumps(todos_los_linters) # Pasar como JSON
    )


@app.route('/docente/editar_examen/<int:examen_id>', methods=['GET', 'POST'])
@login_required
def editar_examen(examen_id):
    """Ruta para editar un examen existente."""
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))

    # Cargar examen con relaciones necesarias de forma eficiente para evitar N+1 queries
    examen = Examen.query.options(
        db.joinedload(Examen.configuracion_examen), # Cargar configuración en la misma query
        db.joinedload(Examen.preguntas).subqueryload(Pregunta.casos_de_prueba) # Cargar preguntas y luego casos
    ).get_or_404(examen_id)

    # Verificar permiso de acceso
    if examen.horario not in current_user.horarios:
        flash('No tienes acceso a este examen.', 'danger')
        return redirect(url_for('dashboard'))

    # Instanciar el formulario de edición
    form = EditarExamenForm()

    # Variable para el estado del flag global, con default por si no existe config
    global_formato_habilitado = getattr(examen.configuracion_examen, 'habilitar_formato', True)

    # --- Variable para pasar al template ---
    global_formato_habilitado = getattr(examen.configuracion_examen, 'habilitar_formato', True)

    # --- INICIO: Poblar CHOICES para el método POST ---
    # Esto es crucial para que validate_on_submit() funcione con los SelectFields dinámicos
    if request.method == 'POST':
        print("Procesando POST /docente/editar_examen - Poblando Choices Linter ANTES de validar")
        # Iterar sobre los subformularios de pregunta que WTForms crea a partir del request
        for i, pregunta_subform in enumerate(form.preguntas):
            try:
                # Obtener el lenguaje seleccionado para esta pregunta específica DESDE EL FORMULARIO ENVIADO
                lenguaje_seleccionado = request.form.get(f'preguntas-{i}-lenguaje_programacion')
                print(f"  Poblando choices pregunta {i}, lenguaje POST: {lenguaje_seleccionado}")
                opciones_linter = [('', '--- Ninguno ---')] # Default
                if lenguaje_seleccionado:
                    # Consultar las herramientas/perfiles para ese lenguaje
                    herramientas = HerramientaAnalisis.query.filter_by(
                        lenguaje=lenguaje_seleccionado
                    ).order_by(HerramientaAnalisis.nombre_mostrado).all()
                    opciones_linter.extend([(h.nombre, h.nombre_mostrado) for h in herramientas])

                # ASIGNAR LAS CHOICES AL CAMPO DEL FORMULARIO ANTES DE LA VALIDACIÓN
                pregunta_subform.linter_perfil.choices = opciones_linter
                print(f"    Choices asignadas para pregunta {i}: {opciones_linter}")

            except Exception as e_choices_post:
                 # Manejar error pero asignar choices vacías para evitar fallo total
                 print(f"Error poblando choices POST para pregunta {i}: {e_choices_post}", file=sys.stderr)
                 pregunta_subform.linter_perfil.choices = [('', '--- Error ---')]
    # --- FIN: Poblar CHOICES para POST ---

    # --- Lógica para Método GET (Poblar el formulario) ---
    if request.method == 'GET':
        print(f"Procesando GET para /docente/editar_examen/{examen_id}")
        # Poblar campos básicos del examen
        form.titulo.data = examen.titulo
        form.descripcion.data = examen.descripcion
        form.fecha_cierre.data = examen.fecha_cierre

        # Poblar flags globales de configuración desde la BD
        if examen.configuracion_examen:
            form.habilitar_formato.data = examen.configuracion_examen.habilitar_formato
            form.habilitar_metricas.data = examen.configuracion_examen.habilitar_metricas
            form.habilitar_similitud.data = examen.configuracion_examen.habilitar_similitud
            form.habilitar_rendimiento.data = examen.configuracion_examen.habilitar_rendimiento
            # Actualizar la variable para el template por si acaso
            global_formato_habilitado = form.habilitar_formato.data
        else:
            # Si no hay config, los campos booleanos del form usarán su 'default'
            # o serán False si no tienen default. Forzar el estado aquí si es necesario.
            form.habilitar_formato.data = True # O False, según tu lógica de default
            global_formato_habilitado = form.habilitar_formato.data
            form.habilitar_metricas.data = True
            form.habilitar_similitud.data = True
            form.habilitar_rendimiento.data = True # O False

        # --- Poblar FieldList de Preguntas usando append_entry(data_dict) ---
        form.preguntas.entries = [] # Limpiar antes de poblar
        for pregunta in sorted(examen.preguntas, key=lambda p: p.id):
            config_formato = pregunta.obtener_configuracion_formato()
            pregunta_data_dict = {
                'enunciado': pregunta.enunciado,
                'puntaje_total': pregunta.puntaje_total,
                'lenguaje_programacion': pregunta.lenguaje_programacion,
                'rubrica_evaluacion': pregunta.rubrica_evaluacion or "", # Usar "" si es None
                'linter_perfil': config_formato.get('perfil', '') if config_formato else '',
                'linter_args_adicionales': config_formato.get('args_adicionales', '') if config_formato else '',
                'casos_de_prueba': []
            }
            for caso in sorted(pregunta.casos_de_prueba, key=lambda c: c.id):
                 caso_data_dict = {
                     'descripcion': caso.descripcion,
                     'argumentos': caso.argumentos,
                     'entrada': caso.entrada,
                     'salida_esperada': caso.salida_esperada,
                     'puntos': caso.puntos,
                     'es_oculto': caso.es_oculto
                 }
                 pregunta_data_dict['casos_de_prueba'].append(caso_data_dict)

            # Añadir el diccionario de datos para esta pregunta
            form.preguntas.append_entry(pregunta_data_dict)
            print(f"  Pregunta {pregunta.id} poblada en formulario.")

    # --- Lógica para Método POST (Validar y Guardar) ---
    # La poblacion de choices para linter_perfil en POST no es necesaria,
    # WTForms valida contra los datos enviados, no contra las choices actuales.
    if form.validate_on_submit():
        print(f"Procesando POST válido para /docente/editar_examen/{examen_id}")
        try:
            # Usar transacción
            with db.session.begin_nested():
                # Actualizar datos del Examen
                examen.titulo = form.titulo.data
                examen.descripcion = form.descripcion.data
                examen.fecha_cierre = form.fecha_cierre.data
                print(f"  Examen {examen.id} actualizado en sesión.")

                # Actualizar/Crear ConfiguracionExamen
                config = examen.configuracion_examen
                if not config:
                    config = ConfiguracionExamen(examen_id=examen.id)
                    db.session.add(config)
                    print(f"  ConfiguracionExamen creada para Examen {examen.id}.")
                config.habilitar_formato = form.habilitar_formato.data
                config.habilitar_metricas = form.habilitar_metricas.data
                config.habilitar_similitud = form.habilitar_similitud.data
                config.habilitar_rendimiento = form.habilitar_rendimiento.data
                print(f"  ConfiguracionExamen actualizada en sesión.")

                # --- Estrategia: Borrar y Recrear Preguntas/Casos ---
                print("  Eliminando preguntas y casos antiguos...")
                # Eliminar casos explícitamente primero
                pregunta_ids_a_borrar = [p.id for p in examen.preguntas]
                if pregunta_ids_a_borrar:
                     CasoDePrueba.query.filter(CasoDePrueba.pregunta_id.in_(pregunta_ids_a_borrar)).delete(synchronize_session=False)
                     Pregunta.query.filter(Pregunta.examen_id == examen.id).delete(synchronize_session=False)
                     db.session.flush() # Aplicar deletes antes de añadir
                print("  Preguntas y casos antiguos eliminados.")

                print("  Añadiendo nuevas preguntas y casos desde el formulario...")
                for i, pregunta_form_data in enumerate(form.preguntas.data):
                    print(f"    Procesando pregunta índice {i}...")
                    # Crear JSON de configuración de formato
                    config_formato = None
                    perfil_linter = pregunta_form_data.get('linter_perfil')
                    args_adicionales = pregunta_form_data.get('linter_args_adicionales', '')

                    if form.habilitar_formato.data and perfil_linter: # Usar flag global del form
                        config_formato = {"perfil": perfil_linter, "args_adicionales": args_adicionales or ""}
                    config_formato_json = json.dumps(config_formato) if config_formato else None
                    print(f"      Config formato JSON: {config_formato_json}")

                    nueva_pregunta = Pregunta(
                        enunciado=pregunta_form_data['enunciado'],
                        puntaje_total=pregunta_form_data['puntaje_total'],
                        lenguaje_programacion=pregunta_form_data['lenguaje_programacion'],
                        rubrica_evaluacion=pregunta_form_data.get('rubrica_evaluacion') or None,
                        configuracion_formato_json=config_formato_json,
                        examen_id=examen.id # Asociar al examen actual
                    )
                    db.session.add(nueva_pregunta)
                    db.session.flush() # Obtener ID

                    # Guardar casos de prueba anidados
                    for j, caso_data in enumerate(pregunta_form_data.get('casos_de_prueba', [])):
                        print(f"      Añadiendo caso índice {j} para pregunta {nueva_pregunta.id}")
                        nuevo_caso = CasoDePrueba(
                             descripcion=caso_data.get('descripcion'),
                             argumentos=caso_data.get('argumentos'),
                             entrada=caso_data.get('entrada'),
                             salida_esperada=caso_data.get('salida_esperada'),
                             puntos=caso_data['puntos'],
                             es_oculto=caso_data.get('es_oculto', False),
                             pregunta_id=nueva_pregunta.id
                         )
                        db.session.add(nuevo_caso)

            # Commit de la transacción principal
            db.session.commit()
            print(f"Examen {examen_id} actualizado exitosamente en BD.")
            flash('Examen actualizado exitosamente.', 'success')
            return redirect(url_for('gestionar_examenes'))

        except Exception as e:
            db.session.rollback() # Rollback si algo falla
            flash('Ocurrió un error grave al actualizar el examen. No se guardaron los cambios.', 'danger')
            print(f"Error al editar examen {examen_id}: {e}", file=sys.stderr)
            # Volver a renderizar con errores - Necesitamos linters y flag global
            global_formato_habilitado = form.habilitar_formato.data # Usar valor del form fallido

    # --- GET o POST con error: Obtener TODOS los linters y pasarlos al template ---
    print("Obteniendo linters para renderizar formulario...")
    todos_los_linters = {}
    try:
        # Obtener todos los lenguajes definidos en LENGUAJES_SOPORTADOS
        codigos_lenguaje = [lang[0] for lang in LENGUAJES_SOPORTADOS]
        for lenguaje_codigo in codigos_lenguaje:
            opciones = [('', '--- Ninguno ---')] # Opción por defecto
            # Consultar herramientas para este lenguaje
            herramientas = HerramientaAnalisis.query.filter_by(
                lenguaje=lenguaje_codigo
            ).order_by(HerramientaAnalisis.nombre_mostrado).all()
            opciones.extend([(h.nombre, h.nombre_mostrado) for h in herramientas])
            todos_los_linters[lenguaje_codigo] = opciones
        print(f"Linters obtenidos para {len(todos_los_linters)} lenguajes.")
    except Exception as e:
        flash('Error al cargar opciones de linter.', 'warning')
        print(f"Error obteniendo linters para formulario: {e}", file=sys.stderr)
        # Crear defaults vacíos en caso de error
        for lc in [lang[0] for lang in LENGUAJES_SOPORTADOS]:
            todos_los_linters[lc] = [('', '--- Error ---')]

    # Obtener estado actual del flag global si es GET
    if request.method == 'GET':
        global_formato_habilitado = getattr(examen.configuracion_examen, 'habilitar_formato', True)
    # Si es POST con error, global_formato_habilitado ya tiene el valor del form

    curso_asociado = examen.horario.oferta_de_curso.curso
    return render_template(
        'crear_examen.html', # Reutilizar la misma plantilla
        form=form, # Pasar el formulario poblado (o con errores)
        editar=True,
        examen_id=examen.id,
        curso=curso_asociado,
        examen=examen,
        global_formato_habilitado=global_formato_habilitado, # Pasar flag
        todos_los_linters_json=json.dumps(todos_los_linters) # Pasar linters
    )


@app.route('/docente/eliminar_examen/<int:examen_id>', methods=['POST'])
@login_required
def eliminar_examen(examen_id):
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        with db.session.begin_nested():  # Create a savepoint
            examen = Examen.query.get_or_404(examen_id)
            
            # Verify access
            if examen.horario not in current_user.horarios:
                flash('No tienes acceso a este examen.', 'danger')
                return redirect(url_for('dashboard'))

            # Get all questions for this exam
            preguntas_ids = [p.id for p in examen.preguntas]
            
            if preguntas_ids:
                # First, find all submissions related to this exam's questions
                entregas = Entrega.query.filter(Entrega.pregunta_id.in_(preguntas_ids)).all()
                
                for entrega in entregas:
                    # Delete evaluation results for each submission
                    if entrega.evaluacion:
                        # Delete evaluation result records
                        ResultadoDeEvaluacion.query.filter_by(evaluacion_id=entrega.evaluacion.id).delete()
                        # Delete the evaluation itself
                        db.session.delete(entrega.evaluacion)
                    
                    # Delete analysis results for the submission
                    AnalisisResultado.query.filter_by(entrega_id=entrega.id).delete()
                    
                    # Delete the submission
                    db.session.delete(entrega)
                
                # Delete exam-user relationships
                UsuarioExamen.query.filter_by(examen_id=examen.id).delete()
                
                # Delete all test cases for each question
                CasoDePrueba.query.filter(CasoDePrueba.pregunta_id.in_(preguntas_ids)).delete()
                
                # Delete all questions
                Pregunta.query.filter(Pregunta.examen_id == examen.id).delete()
            
            # Delete exam configuration if it exists
            if examen.configuracion_examen:
                db.session.delete(examen.configuracion_examen)
            
            # Finally delete the exam
            db.session.delete(examen)
            
        # If everything went well, commit the transaction
        db.session.commit()
        flash('Examen y todos sus componentes eliminados exitosamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el examen: {str(e)}', 'danger')
        print(f"Error al eliminar examen: {e}")  # For debugging
    
    return redirect(url_for('gestionar_examenes'))

@app.route('/ver_examenes')
@login_required
def ver_examenes():
    horarios = current_user.horarios
    examenes = Examen.query.filter(Examen.horario_id.in_([h.id for h in horarios])).all()
    return render_template('ver_examenes.html', examenes=examenes)

@app.route('/mis_entregas')
@login_required
def mis_entregas():
    # Get all submissions for the current user
    entregas = current_user.entregas.all()  # Using .all() to convert to a list
    
    # Filter out entries with None relationships to prevent template errors
    valid_entregas = []
    for entrega in entregas:
        if (entrega and entrega.pregunta and 
            entrega.pregunta.examen):
            valid_entregas.append(entrega)
        else:
            print(f"Skipping entrega {entrega.id} due to missing relationships")
    
    # Sort by submission date (most recent first)
    valid_entregas.sort(key=lambda e: e.fecha_entrega, reverse=True)
    
    return render_template('mis_entregas.html', entregas=valid_entregas)

@app.route('/ver_resultados_alumno')
@login_required
def ver_resultados_alumno():
    evaluaciones = current_user.evaluaciones
    return render_template('ver_resultados_alumno.html', evaluaciones=evaluaciones)

@app.route('/docente/ver_resultados')
@login_required
def ver_resultados():
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Obtener parámetros de filtro (si existen)
    examen_id = request.args.get('examen_id', type=int)
    curso_id = request.args.get('curso_id', type=int)
    
    # Obtener las evaluaciones filtradas (últimas entregas de cada alumno por pregunta)
    evaluaciones = obtener_evaluaciones_por_examen(examen_id, curso_id)
    
    # Calcular estadísticas basadas en las evaluaciones filtradas
    estadisticas = calcular_estadisticas_evaluaciones(evaluaciones)
    
    # Obtener lista de cursos y exámenes para los filtros
    cursos, examenes = obtener_cursos_y_examenes_docente(current_user.id)
    
    # Renderizar la plantilla con todos los datos calculados
    return render_template(
        'ver_resultados.html', 
        evaluaciones=evaluaciones,
        estadisticas=estadisticas, 
        cursos=cursos,
        examenes=examenes,
        filtro_examen_id=examen_id,
        filtro_curso_id=curso_id
    )

@app.route('/docente/ver_detalle_evaluacion/<int:evaluacion_id>')
@login_required
def ver_detalle_evaluacion(evaluacion_id):
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))
    
    evaluacion = Evaluacion.query.get_or_404(evaluacion_id)
    
    # Verificar que la evaluación pertenece a un examen del docente
    if evaluacion.entrega.pregunta.examen.horario not in current_user.horarios:
        flash('No tienes permiso para ver esta evaluación.', 'danger')
        return redirect(url_for('ver_resultados'))
    
    # Obtener todas las entregas de este alumno para esta pregunta
    entregas_alumno = Entrega.query.filter_by(
        alumno_id=evaluacion.entrega.alumno_id,
        pregunta_id=evaluacion.entrega.pregunta_id
    ).order_by(Entrega.fecha_entrega.desc()).all()
    
    # Obtener las evaluaciones de esas entregas
    historial_evaluaciones = []
    for entrega in entregas_alumno:
        if entrega.evaluacion:
            historial_evaluaciones.append(entrega.evaluacion)
    
    return render_template(
        'ver_detalle_evaluacion.html', 
        evaluacion=evaluacion,
        historial_evaluaciones=historial_evaluaciones
    )

@app.route('/docente/examen/<int:examen_id>/agregar_pregunta', methods=['GET', 'POST'])
@login_required
def agregar_pregunta(examen_id):
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))
    
    examen = Examen.query.get_or_404(examen_id)
    if examen.horario not in current_user.horarios:
        flash('No tienes acceso a este examen.', 'danger')
        return redirect(url_for('dashboard'))
    
    form = PreguntaForm()
    if form.validate_on_submit():
        nueva_pregunta = Pregunta(
            enunciado=form.enunciado.data,
            puntaje_total=form.puntaje_total.data,
            lenguaje_programacion=form.lenguaje_programacion.data,
            examen_id=examen.id
        )
        db.session.add(nueva_pregunta)
        db.session.commit()
        
        for caso_form in form.casos_de_prueba.entries:
            nuevo_caso = CasoDePrueba(
                entrada=caso_form.entrada.data,
                salida_esperada=caso_form.salida_esperada.data,
                pregunta_id=nueva_pregunta.id
            )
            db.session.add(nuevo_caso)
        
        db.session.commit()
        
        flash('Pregunta y sus casos de prueba agregados exitosamente.', 'success')
        return redirect(url_for('ver_examen', examen_id=examen.id))
    
    return render_template('agregar_pregunta.html', form=form, examen=examen)


@app.route('/docente/pregunta/<int:pregunta_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_pregunta(pregunta_id):
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))
    
    pregunta = Pregunta.query.get_or_404(pregunta_id)
    examen = pregunta.examen
    if examen.horario not in current_user.horarios:
        flash('No tienes acceso a esta pregunta.', 'danger')
        return redirect(url_for('dashboard'))
    
    form = PreguntaForm(obj=pregunta)
    if form.validate_on_submit():
        pregunta.enunciado = form.enunciado.data
        pregunta.puntaje_total = form.puntaje_total.data
        pregunta.lenguaje_programacion = form.lenguaje_programacion.data
        db.session.commit()
        
        flash('Pregunta actualizada exitosamente.', 'success')
        return redirect(url_for('ver_examen', examen_id=examen.id))
    
    return render_template('editar_pregunta.html', form=form, examen=examen, pregunta=pregunta)

@app.route('/docente/pregunta/<int:pregunta_id>/eliminar', methods=['POST'])
@login_required
def eliminar_pregunta(pregunta_id):
    if current_user.rol != 'docente':
        flash('Acceso no autorizado.', 'danger')
        return redirect(url_for('dashboard'))
    
    pregunta = Pregunta.query.get_or_404(pregunta_id)
    examen = pregunta.examen
    if examen.horario not in current_user.horarios:
        flash('No tienes acceso a esta pregunta.', 'danger')
        return redirect(url_for('dashboard'))
    
    db.session.delete(pregunta)
    db.session.commit()
    
    flash('Pregunta eliminada exitosamente.', 'success')
    return redirect(url_for('ver_examen', examen_id=examen.id))

@app.route('/mis_evaluaciones')
@login_required
def mis_evaluaciones():
    # --- VERIFY THESE LINES ---
    # Ensure 'request.args.get' defaults to None correctly.
    # Using type=int will return None if the parameter is missing or not a valid integer.
    examen_id = request.args.get('examen_id', default=None, type=int)
    curso_id = request.args.get('curso_id', default=None, type=int)

    # --- ADD DEBUGGING ---
    # Print the values *immediately* after getting them from the request
    print(f"DEBUG: /mis_evaluaciones - Request Args - curso_id: {request.args.get('curso_id')}, examen_id: {request.args.get('examen_id')}")
    print(f"DEBUG: /mis_evaluaciones - Parsed IDs - curso_id: {curso_id}, examen_id: {examen_id}")
    # --- END DEBUGGING ---

    # Consulta base para obtener evaluaciones del alumno
    query = Evaluacion.query.join(Entrega).filter(Entrega.alumno_id == current_user.id)

    # Aplicar filtros si se proporcionan *and they are not None*
    if examen_id is not None: # Explicit check for None
        query = query.join(Pregunta, Entrega.pregunta_id == Pregunta.id)\
                    .filter(Pregunta.examen_id == examen_id)

    if curso_id is not None: # Explicit check for None
        # Ensure the join order makes sense if filtering by both
        if examen_id is None: # Avoid joining Pregunta twice if already done
             query = query.join(Pregunta, Entrega.pregunta_id == Pregunta.id)
        query = query.join(Examen, Pregunta.examen_id == Examen.id)\
                    .join(Horario, Examen.horario_id == Horario.id)\
                    .join(OfertaDeCurso, Horario.oferta_de_curso_id == OfertaDeCurso.id)\
                    .filter(OfertaDeCurso.curso_id == curso_id)

    # Obtener las evaluaciones filtradas
    # Order by date might be useful
    evaluaciones = query.order_by(Entrega.fecha_entrega.desc()).all()

    evaluaciones = [eval for eval in evaluaciones if eval.entrega.pregunta is not None]

    # Calcular estadísticas (this function seems fine)
    estadisticas = calculate_student_stats(evaluaciones) # Renamed for clarity

    # Obtener lista de cursos y exámenes para filtros (this function seems fine)
    cursos, examenes = get_student_courses_and_exams(current_user) # Renamed for clarity

    # --- ADD DEBUGGING ---
    # Print the values being passed to the template
    print(f"DEBUG: /mis_evaluaciones - Passing to template - filtro_curso_id: {curso_id}, filtro_examen_id: {examen_id}")
    # --- END DEBUGGING ---

    return render_template(
        'mis_evaluaciones.html',
        evaluaciones=evaluaciones,
        estadisticas=estadisticas,
        cursos=cursos,
        examenes=examenes,
        # Pass the *parsed* IDs to the template
        filtro_examen_id=examen_id,
        filtro_curso_id=curso_id
    )

# Helper function to calculate stats (moved logic here for clarity)
def calculate_student_stats(evaluaciones):
    stats_data = {
        'total_evaluaciones': len(evaluaciones),
        'promedio_general': 0,
        'examenes_unicos': 0,
        'distribuciones': [0, 0, 0, 0, 0],
        'rendimiento_examenes': {}
    }
    if not evaluaciones:
        return stats_data

    total_puntos = 0
    total_max_puntos = 0
    examenes_ids = set()
    examen_stats = defaultdict(lambda: {'total_puntos': 0, 'max_puntos': 0, 'count': 0})

    for eval_obj in evaluaciones:
        try:
            examen = eval_obj.entrega.pregunta.examen
            pregunta = eval_obj.entrega.pregunta

            examenes_ids.add(examen.id)
            puntos = eval_obj.puntaje_obtenido
            max_puntos = pregunta.puntaje_total

            total_puntos += puntos
            total_max_puntos += max_puntos

            examen_titulo = examen.titulo
            examen_stats[examen_titulo]['total_puntos'] += puntos
            examen_stats[examen_titulo]['max_puntos'] += max_puntos
            examen_stats[examen_titulo]['count'] += 1

            if max_puntos > 0:
                porcentaje = (puntos / max_puntos) * 100
                if porcentaje <= 20: stats_data['distribuciones'][0] += 1
                elif porcentaje <= 40: stats_data['distribuciones'][1] += 1
                elif porcentaje <= 60: stats_data['distribuciones'][2] += 1
                elif porcentaje <= 80: stats_data['distribuciones'][3] += 1
                else: stats_data['distribuciones'][4] += 1
        except AttributeError as e:
             # Handle cases where related objects might be missing unexpectedly
             print(f"WARN: Skipping evaluation due to AttributeError: {e} - Eval ID: {eval_obj.id}")
             continue # Skip this evaluation if data is incomplete

    if total_max_puntos > 0:
        stats_data['promedio_general'] = round((total_puntos / total_max_puntos) * 100, 1)

    for examen, stats in examen_stats.items():
        if stats['max_puntos'] > 0:
            stats_data['rendimiento_examenes'][examen] = round((stats['total_puntos'] / stats['max_puntos']) * 100, 1)
        else:
            stats_data['rendimiento_examenes'][examen] = 0

    stats_data['examenes_unicos'] = len(examenes_ids)
    return stats_data

# Helper function to get filters (moved logic here for clarity)
def get_student_courses_and_exams(student_user):
    cursos_dict = {}
    examenes_list = []
    try:
        for horario in student_user.horarios:
            curso = horario.oferta_de_curso.curso
            if curso.id not in cursos_dict:
                cursos_dict[curso.id] = {
                    'id': curso.id,
                    'nombre': curso.nombre,
                    'codigo': curso.codigo
                }

            for examen in horario.examenes:
                # Check if student has *any* entrega for this exam's questions
                tiene_entregas = db.session.query(Entrega.id).join(Pregunta).filter(
                    Entrega.alumno_id == student_user.id,
                    Pregunta.examen_id == examen.id
                ).limit(1).scalar() is not None # Efficient check

                if tiene_entregas:
                    examenes_list.append({
                        'id': examen.id,
                        'titulo': examen.titulo,
                        'curso_id': curso.id,
                        'curso_nombre': curso.nombre
                    })
    except Exception as e:
         print(f"ERROR fetching courses/exams for student {student_user.id}: {e}")
         # Return empty lists on error to prevent crashes
         return [], []

    # Sort for consistent dropdown order
    sorted_cursos = sorted(list(cursos_dict.values()), key=lambda c: c['codigo'])
    sorted_examenes = sorted(examenes_list, key=lambda ex: (ex['curso_nombre'], ex['titulo']))

    return sorted_cursos, sorted_examenes

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

