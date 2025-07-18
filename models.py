# models.py

from extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import json
from typing import Optional, Dict, Any

# Tabla de asociación entre usuarios y horarios
usuario_horario = db.Table('usuario_horario',
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuario.id'), primary_key=True),
    db.Column('horario_id', db.Integer, db.ForeignKey('horario.id'), primary_key=True)
)

# ===============================
# MODELOS DE USUARIO, CURSOS, CICLOS, HORARIOS, EXAMEN, PREGUNTAS, CASOS, ENTREGA Y EVALUACIÓN
# ===============================

class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuario'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    codigo = db.Column(db.String(20), unique=True, nullable=True, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    contrasena = db.Column(db.String(128), nullable=False)
    rol = db.Column(db.String(20), nullable=False)  # 'docente' o 'alumno'
    estado = db.Column(db.String(20), nullable=False, default="activo")

    # Relaciones
    horarios = db.relationship('Horario', secondary=usuario_horario, back_populates='usuarios', lazy='joined')
    entregas = db.relationship('Entrega', backref='alumno', lazy='dynamic', foreign_keys='Entrega.alumno_id')
    historial_de_examenes = db.relationship('Examen', secondary='usuario_examen', backref='usuarios', lazy='dynamic')

    def set_password(self, password):
        self.contrasena = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.contrasena, password)

    __table_args__ = (
        db.Index('ix_usuario_email', 'email'),  # Índice para mejorar las consultas por email
    )

class UsuarioExamen(db.Model):
    __tablename__ = 'usuario_examen'
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), primary_key=True)
    examen_id = db.Column(db.Integer, db.ForeignKey('examen.id'), primary_key=True)
    fecha_realizado = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    calificacion = db.Column(db.Float, nullable=True)
    estado = db.Column(db.String(50), nullable=True, default='pendiente')

    __table_args__ = (
        db.Index('ix_usuario_examen_usuario', 'usuario_id'),  # Índice para mejorar las consultas por usuario
        db.Index('ix_usuario_examen_examen', 'examen_id'),  # Índice para mejorar las consultas por examen
    )

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

class Curso(db.Model):
    __tablename__ = 'curso'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    codigo = db.Column(db.String(20), nullable=False)

    # Relaciones
    ofertas_de_curso = db.relationship('OfertaDeCurso', backref='curso', lazy=True)

    __table_args__ = (
        db.Index('ix_curso_codigo', 'codigo'),  # Índice para mejorar las consultas por código de curso
    )

class CicloAcademico(db.Model):
    __tablename__ = 'ciclo_academico'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)

    # Relaciones
    ofertas_de_curso = db.relationship('OfertaDeCurso', backref='ciclo_academico', lazy=True)

class OfertaDeCurso(db.Model):
    __tablename__ = 'oferta_de_curso'
    id = db.Column(db.Integer, primary_key=True)
    curso_id = db.Column(db.Integer, db.ForeignKey('curso.id'), nullable=False)
    ciclo_academico_id = db.Column(db.Integer, db.ForeignKey('ciclo_academico.id'), nullable=False)

    # Relaciones
    horarios = db.relationship('Horario', backref='oferta_de_curso', lazy='joined')

    __table_args__ = (
        db.Index('ix_oferta_de_curso_ciclo_academico', 'ciclo_academico_id'),  # Índice para mejorar las consultas por ciclo académico
    )

class Horario(db.Model):
    __tablename__ = 'horario'
    id = db.Column(db.Integer, primary_key=True)
    oferta_de_curso_id = db.Column(db.Integer, db.ForeignKey('oferta_de_curso.id'), nullable=False)
    nombre = db.Column(db.String(50), nullable=False)

    # Relaciones
    usuarios = db.relationship('Usuario', secondary=usuario_horario, back_populates='horarios', lazy='joined')
    examenes = db.relationship('Examen', backref='horario', lazy=True)

    @property
    def alumnos(self):
        return [usuario for usuario in self.usuarios if usuario.rol == 'alumno']

    @property
    def docentes(self):
        return [usuario for usuario in self.usuarios if usuario.rol == 'docente']

class Examen(db.Model):
    __tablename__ = 'examen'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    fecha_publicacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fecha_cierre = db.Column(db.DateTime, nullable=False)
    horario_id = db.Column(db.Integer, db.ForeignKey('horario.id'), nullable=False)

    # Relaciones
    preguntas = db.relationship('Pregunta', backref='examen', lazy=True, cascade="all, delete-orphan")
    configuracion_examen = db.relationship('ConfiguracionExamen', back_populates='examen', uselist=False)

    __table_args__ = (
        db.Index('ix_examen_titulo', 'titulo'),  # Índice para mejorar las consultas por título de examen
    )

class ConfiguracionExamen(db.Model):
    __tablename__ = 'configuracion_examen'
    id = db.Column(db.Integer, primary_key=True)
    examen_id = db.Column(db.Integer, db.ForeignKey('examen.id'), nullable=False)
    examen = db.relationship('Examen', back_populates='configuracion_examen')
    
    habilitar_formato = db.Column(db.Boolean, default=True)
    habilitar_metricas = db.Column(db.Boolean, default=True)
    habilitar_similitud = db.Column(db.Boolean, default=True)
    habilitar_rendimiento = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<ConfiguracionExamen examen_id={self.examen_id}>'

class Pregunta(db.Model):
    __tablename__ = 'pregunta'
    id = db.Column(db.Integer, primary_key=True)
    enunciado = db.Column(db.Text, nullable=False)
    puntaje_total = db.Column(db.Float, nullable=False)
    lenguaje_programacion = db.Column(db.String(50), nullable=False)
    solucion_modelo = db.Column(db.Text, nullable=True)
    rubrica_evaluacion = db.Column(db.Text, nullable=True, comment="Rubrica en formato JSON para la evaluación con LLM")
    examen_id = db.Column(db.Integer, db.ForeignKey('examen.id'), nullable=False)

    configuracion_formato_json = db.Column(
        db.Text,
        nullable=True,
        comment='Configuración del linter en JSON. Ej: {"perfil": "flake8", "args_adicionales": "--ignore=E501"}'
    )

    # Relaciones
    casos_de_prueba = db.relationship('CasoDePrueba', backref='pregunta', lazy=True, cascade="all, delete-orphan")
    entregas = db.relationship('Entrega', backref='pregunta', lazy='dynamic')

    # Helper para parsear el JSON (recomendado)
    def obtener_configuracion_formato(self) -> Optional[Dict[str, Any]]:
        if not self.configuracion_formato_json:
            return None
        try:
            return json.loads(self.configuracion_formato_json)
        except json.JSONDecodeError:
            print(f"WARN: Error decoding JSON config for Pregunta {self.id}: {self.configuracion_formato_json}")
            return None

class CasoDePrueba(db.Model):
    __tablename__ = 'caso_de_prueba'
    id = db.Column(db.Integer, primary_key=True)

    descripcion = db.Column(db.Text, nullable=False)
    argumentos = db.Column(db.Text, nullable=False)
    entrada = db.Column(db.Text, nullable=True, default="")
    salida_esperada = db.Column(db.Text, nullable=True, default="")
    puntos = db.Column(db.Float, nullable=False)
    es_oculto = db.Column(db.Boolean, default=False)

    pregunta_id = db.Column(db.Integer, db.ForeignKey('pregunta.id'), nullable=False)

    # Relaciones
    resultados = db.relationship('ResultadoDeEvaluacion', backref='caso_de_prueba', lazy='dynamic')

    # Metodo helper para obtener los argumentos como una lista
    def obtener_argumentos(self):
        if not self.argumentos:
            return []
        try:
            args = json.loads(self.argumentos)
            if isinstance(args, list):
                return [str(arg) for arg in args]
            else:
                print(f"Error: Los argumentos no son una lista válida. {args}")
                return []
        except json.JSONDecodeError:
            print(f"Error: No se pudo decodificar los argumentos JSON. {self.argumentos}")
            return []
    
class Entrega(db.Model):
    __tablename__ = 'entrega'
    id = db.Column(db.Integer, primary_key=True)
    fecha_entrega = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    codigo_fuente = db.Column(db.Text, nullable=False)
    archivo = db.Column(db.String(120), nullable=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    pregunta_id = db.Column(db.Integer, db.ForeignKey('pregunta.id'), nullable=False)

    evaluacion = db.relationship('Evaluacion', backref='entrega', uselist=False)
    analisis_resultados = db.relationship(
        'AnalisisResultado',
        back_populates='entrega', # Usar back_populates
        lazy='dynamic', # Cambiado a dynamic para que sea una query
        cascade='all, delete-orphan'
    )

class Evaluacion(db.Model):
    __tablename__ = 'evaluacion'
    id = db.Column(db.Integer, primary_key=True)
    puntaje_obtenido = db.Column(db.Float, nullable=False)
    feedback = db.Column(db.Text, nullable=True)
    feedback_llm_general = db.Column(db.Text, nullable=True, comment="Feedback cualitativo general del LLM")
    fecha_evaluacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    entrega_id = db.Column(db.Integer, db.ForeignKey('entrega.id'), nullable=False)

    # Relaciones
    resultados = db.relationship('ResultadoDeEvaluacion', backref='evaluacion', lazy=True)
    resultados_criterios_llm = db.relationship('ResultadoCriterioLLM', backref='evaluacion', lazy='dynamic', cascade="all, delete-orphan")

class ResultadoCriterioLLM(db.Model):
    __tablename__ = 'resultado_criterio_llm'
    id = db.Column(db.Integer, primary_key=True)
    evaluacion_id = db.Column(db.Integer, db.ForeignKey('evaluacion.id', ondelete='CASCADE'), nullable=False)
    criterio_nombre = db.Column(db.String(255), nullable=False, index=True) # Añadido index
    puntaje_obtenido_llm = db.Column(db.Float, nullable=False)
    max_puntaje_criterio = db.Column(db.Float, nullable=True) # Puntaje máximo para este criterio según la rúbrica
    feedback_criterio_llm = db.Column(db.Text, nullable=True)

    # La relación inversa 'evaluacion' ya está definida en Evaluacion.resultados_criterios_llm
    # No necesitas un db.relationship aquí a menos que quieras una configuración específica para esta dirección.

    def __repr__(self):
        return f'<ResultadoCriterioLLM id={self.id} criterio="{self.criterio_nombre}" puntaje={self.puntaje_obtenido_llm}>'

class ResultadoDeEvaluacion(db.Model):
    __tablename__ = 'resultado_de_evaluacion'
    id = db.Column(db.Integer, primary_key=True)
    paso = db.Column(db.Boolean, nullable=False)
    salida_obtenida = db.Column(db.Text, nullable=False)
    puntos_obtenidos = db.Column(db.Float, nullable=False)
    evaluacion_id = db.Column(db.Integer, db.ForeignKey('evaluacion.id'), nullable=False)
    caso_de_prueba_id = db.Column(db.Integer, db.ForeignKey('caso_de_prueba.id'), nullable=False)
    # Representaciones detalladas para visualización
    salida_obtenida_repr = db.Column(db.Text, nullable=True, comment="Representación depurable (repr) de la salida obtenida")
    salida_esperada_repr = db.Column(db.Text, nullable=True, comment="Representación depurable (repr) de la salida esperada")
    entrada_repr = db.Column(db.Text, nullable=True, comment="Representación depurable (repr) de la entrada utilizada")
    argumentos_repr = db.Column(db.Text, nullable=True, comment="Representación depurable (repr) de los argumentos utilizados")
    
    # Salida de error (stderr)
    stderr_obtenido = db.Column(db.Text, nullable=True, comment="Salida de error si existió durante la ejecución")
    stderr_obtenido_repr = db.Column(db.Text, nullable=True, comment="Representación depurable de stderr")
    
    # Información adicional de tiempo y recursos
    tiempo_ejecucion_ms = db.Column(db.Integer, nullable=True, comment="Tiempo de ejecución en milisegundos")
    memoria_utilizada_kb = db.Column(db.Integer, nullable=True, comment="Memoria utilizada en kilobytes")
    
    # Estado y detalles específicos
    estado_ejecucion = db.Column(db.String(50), nullable=True, 
                                 comment="Estado detallado: 'completado', 'timeout', 'error', etc.")
    codigo_retorno = db.Column(db.Integer, nullable=True, 
                               comment="Código de retorno del proceso ejecutado")
    
    # Información de diferencias
    diferencias_resumen = db.Column(db.Text, nullable=True, 
                                   comment="Resumen de diferencias entre salida esperada y obtenida")
    
    # Campos para auditoría
    fecha_ejecucion = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

# ===============================
# MODELOS PARA LOS MÓDULOS DE ANÁLISIS DE CÓDIGO
# ===============================

class AnalisisMetrica(db.Model):
    __tablename__ = 'analisis_metrica'
    id = db.Column(db.Integer, primary_key=True)
    entrega_id = db.Column(db.Integer, db.ForeignKey('entrega.id', ondelete='CASCADE'), nullable=False)
    metrica = db.Column(db.String(50), nullable=False)
    valor = db.Column(db.Float, nullable=False)

    

class AnalisisSimilitud(db.Model):
    __tablename__ = 'analisis_similitud'
    id = db.Column(db.Integer, primary_key=True)
    entrega_id_1 = db.Column(db.Integer, db.ForeignKey('entrega.id', ondelete='CASCADE'), nullable=False)
    entrega_id_2 = db.Column(db.Integer, db.ForeignKey('entrega.id', ondelete='CASCADE'), nullable=False)
    porcentaje_similitud = db.Column(db.Float, nullable=False)

    # AÑADIDO: Índices para que las búsquedas sean más rápidas
    __table_args__ = (
        db.Index('ix_similitud_entrega1', 'entrega_id_1'),
        db.Index('ix_similitud_entrega2', 'entrega_id_2'),
    )

class AnalisisResultado(db.Model):
    __tablename__ = 'analisis_resultado'
    id = db.Column(db.Integer, primary_key=True)
    entrega_id = db.Column(db.Integer, db.ForeignKey('entrega.id', ondelete='CASCADE'), nullable=False) # ondelete
    # Asegurar FK a herramienta tiene ondelete='SET NULL' o 'RESTRICT' para no perder el nombre si se borra la herramienta
    herramienta_id = db.Column(db.Integer, db.ForeignKey('herramienta_analisis.id', ondelete='SET NULL'), nullable=True) # ondelete
    informe = db.Column(db.Text, nullable=False) # Guarda el reporte del linter o métrica
    puntuacion = db.Column(db.Float, nullable=True) # Significado depende de la herramienta (ej. 1.0/0.0 para linter)
    fecha_analisis = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # Añadido Not Nullable

    # Relaciones (usando back_populates)
    entrega = db.relationship('Entrega', back_populates='analisis_resultados')
    herramienta = db.relationship('HerramientaAnalisis', backref=db.backref('resultados_generados', lazy='dynamic')) # backref ok aquí

class HerramientaAnalisis(db.Model):
    __tablename__ = 'herramienta_analisis'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True) # Identificador interno
    nombre_mostrado = db.Column(db.String(150), nullable=False) # Para UI
    lenguaje = db.Column(db.String(50), nullable=False, index=True)
    # Asegurar FK a tipo_analisis tiene ondelete='SET NULL' o 'RESTRICT'
    tipo_analisis_id = db.Column(db.Integer, db.ForeignKey('tipo_analisis.id', ondelete='SET NULL'), nullable=True) # ondelete
    descripcion = db.Column(db.Text, nullable=True)

    tipo_analisis = db.relationship('TipoAnalisis', backref=db.backref('herramientas', lazy=True)) # backref ok

class TipoAnalisis(db.Model):
    __tablename__ = 'tipo_analisis'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
