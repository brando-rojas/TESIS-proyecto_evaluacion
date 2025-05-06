# import_data.py

import json
from app import app
from extensions import db
from models import (
    Usuario, Curso, CicloAcademico, OfertaDeCurso,
    Horario, Examen, Pregunta, CasoDePrueba,
    Entrega, Evaluacion, ResultadoDeEvaluacion
)
from werkzeug.security import generate_password_hash
from datetime import datetime

def cargar_datos():
    with open('data.json', 'r', encoding='utf-8') as archivo:
        datos = json.load(archivo)

    # ----------------------------
    # Cargar Cursos
    # ----------------------------
    for c in datos['cursos']:
        curso = Curso(
            id=c['id'],
            nombre=c['nombre'],
            codigo=c['codigo']
        )
        db.session.merge(curso)

    # ----------------------------
    # Cargar Ciclos Académicos
    # ----------------------------
    for ca in datos['ciclos_academicos']:
        ciclo = CicloAcademico(
            id=ca['id'],
            nombre=ca['nombre']
        )
        db.session.merge(ciclo)

    # ----------------------------
    # Cargar Ofertas de Curso
    # ----------------------------
    for oc in datos['ofertas_de_curso']:
        oferta = OfertaDeCurso(
            id=oc['id'],
            curso_id=oc['curso_id'],
            ciclo_academico_id=oc['ciclo_academico_id']
        )
        db.session.merge(oferta)

    # ----------------------------
    # Cargar Horarios (Incluyendo 'nombre')
    # ----------------------------
    for h in datos['horarios']:
        horario = Horario(
            id=h['id'],
            oferta_de_curso_id=h['oferta_de_curso_id'],
            nombre=h['nombre']  # Agregado según el nuevo modelo
        )
        db.session.merge(horario)

    # Confirmar los cambios para poder asignar usuarios a horarios
    db.session.commit()

    # ----------------------------
    # Cargar Usuarios (Alumnos y Docentes)
    # ----------------------------
    for a in datos['alumnos']:
        alumno = Usuario(
            id=a['id'],
            nombre=a['nombre'],
            email=a['email'],
            contrasena=a['contrasena'],  # Usar 'contrasena' en lugar de 'contraseña'
            rol=a['rol']  # 'alumno'
        )
        db.session.merge(alumno)

    for d in datos['docentes']:
        docente = Usuario(
            id=d['id'],
            nombre=d['nombre'],
            email=d['email'],
            contrasena=d['contrasena'],  # Usar 'contrasena' en lugar de 'contraseña'
            rol=d['rol']  # 'docente'
        )
        db.session.merge(docente)

    # Confirmar los cambios antes de asignar relaciones muchos a muchos
    db.session.commit()

    # ----------------------------
    # Asignar Usuarios a Horarios mediante 'usuario_horario'
    # ----------------------------
    for hu in datos.get('usuario_horario', []):
        horario = Horario.query.get(hu['horario_id'])
        usuario = Usuario.query.get(hu['usuario_id'])
        if usuario and horario and usuario not in horario.usuarios:
            horario.usuarios.append(usuario)

    # Confirmar las asociaciones
    db.session.commit()

    # ----------------------------
    # Cargar Exámenes
    # ----------------------------
    for e in datos['examenes']:
        examen = Examen(
            id=e['id'],
            titulo=e['titulo'],
            descripcion=e['descripcion'],
            fecha_publicacion=datetime.strptime(e['fecha_publicacion'], '%Y-%m-%dT%H:%M:%S'),
            fecha_cierre=datetime.strptime(e['fecha_cierre'], '%Y-%m-%dT%H:%M:%S'),
            horario_id=e['horario_id']  # Asignar según data.json
        )
        db.session.merge(examen)

    # ----------------------------
    # Cargar Preguntas (Incluyendo 'solucion_modelo')
    # ----------------------------
    for p in datos['preguntas']:
        pregunta = Pregunta(
            id=p['id'],
            enunciado=p['enunciado'],
            puntaje_total=p['puntaje_total'],
            lenguaje_programacion=p['lenguaje_programacion'],
            examen_id=p['examen_id'],
            solucion_modelo=p['solucion_modelo']  # Agregado según el nuevo modelo
        )
        db.session.merge(pregunta)

    # ----------------------------
    # Cargar Casos de Prueba
    # ----------------------------
    for c in datos.get('casos_de_prueba', []):
        caso = CasoDePrueba.query.get(c['id'])
        if not caso:
            caso = CasoDePrueba(id=c['id'])

        # ---> CORRECCIÓN: Leer todos los campos del JSON <---
        #      Asignar un valor default si falta 'descripcion' o 'argumentos'
        #      ya que la BD los requiere (según el error y tu último modelo)
        caso.descripcion = c.get('descripcion', f'Caso de prueba {c["id"]}') # Default si falta
        caso.argumentos = c.get('argumentos', '[]') # Default JSON lista vacía si falta
        caso.entrada = c.get('entrada', '') # Default string vacío si falta

        # Campos que parecían existir en tu JSON
        caso.salida_esperada = c['salida_esperada']
        caso.puntos = c['puntos']
        caso.pregunta_id = c['pregunta_id']
        caso.es_oculto = c.get('es_oculto', False) # Usar .get() con default

        db.session.merge(caso)

    # ----------------------------
    # Cargar Entregas (Si existen)
    # ----------------------------
    if 'entregas' in datos and datos['entregas']:
        for entrega_data in datos['entregas']:
            entrega = Entrega(
                id=entrega_data['id'],
                fecha_entrega=datetime.strptime(entrega_data['fecha_entrega'], '%Y-%m-%dT%H:%M:%S'),
                codigo_fuente=entrega_data['codigo_fuente'],
                alumno_id=entrega_data['alumno_id'],
                pregunta_id=entrega_data['pregunta_id']
            )
            db.session.merge(entrega)

    # ----------------------------
    # Cargar Evaluaciones (Si existen)
    # ----------------------------
    if 'evaluaciones' in datos and datos['evaluaciones']:
        for evaluacion_data in datos['evaluaciones']:
            evaluacion = Evaluacion(
                id=evaluacion_data['id'],
                puntaje_obtenido=evaluacion_data['puntaje_obtenido'],
                feedback=evaluacion_data['feedback'],
                entrega_id=evaluacion_data['entrega_id']
            )
            db.session.merge(evaluacion)

    # ----------------------------
    # Cargar Resultados de Evaluación (Si existen)
    # ----------------------------
    if 'resultados_de_evaluacion' in datos and datos['resultados_de_evaluacion']:
        for resultado_data in datos['resultados_de_evaluacion']:
            resultado = ResultadoDeEvaluacion(
                id=resultado_data['id'],
                paso=resultado_data['paso'],
                salida_obtenida=resultado_data['salida_obtenida'],
                puntos_obtenidos=resultado_data['puntos_obtenidos'],
                evaluacion_id=resultado_data['evaluacion_id'],
                caso_de_prueba_id=resultado_data['caso_de_prueba_id']
            )
            db.session.merge(resultado)

    # Confirmar todos los cambios finales
    db.session.commit()
    print("Datos importados exitosamente.")

if __name__ == '__main__':
    with app.app_context():
        cargar_datos()
