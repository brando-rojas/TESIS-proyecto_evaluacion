# forms.py

from flask_wtf import FlaskForm
from wtforms import SelectMultipleField, StringField, PasswordField, SubmitField, TextAreaField, SelectField, DateTimeField, FloatField, FormField, FieldList, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, NumberRange
from flask_wtf.file import FileField, FileAllowed
from wtforms.validators import ValidationError
import json

LENGUAJES_SOPORTADOS = [
    ('c', 'C'),             # Clave 'c', Label 'C'
    ('python', 'Python'),     # Clave 'python', Label 'Python'
    ('java', 'Java'),
    ('pseint', 'PSeInt')
]

# Validador 1: Solo verifica sintaxis JSON
def validate_json_syntax(form, field):
    """Valida que el texto sea JSON sintácticamente válido."""
    if field.data:
        try:
            json.loads(field.data)
        except json.JSONDecodeError:
            raise ValidationError('Formato JSON inválido.')
        except Exception as e:
             raise ValidationError(f'Error inesperado al validar JSON: {e}')

# Validador 2: Verifica sintaxis JSON Y que sea una LISTA
def validate_json_list(form, field):
    """Valida que el texto sea una lista JSON válida."""
    if field.data:
        try:
            data = json.loads(field.data)
            if not isinstance(data, list):
                raise ValidationError('Debe ser una lista JSON válida (ej: ["arg1", "arg2"]).')
        except json.JSONDecodeError:
            raise ValidationError('Formato JSON inválido.')
        except Exception as e:
             raise ValidationError(f'Error inesperado al validar JSON: {e}')

class RegistroForm(FlaskForm):
    nombre = StringField('Nombre', validators=[DataRequired(), Length(min=2, max=150)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    contraseña = PasswordField('Contraseña', validators=[DataRequired(), Length(min=6)])
    confirmar_contraseña = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('contraseña')])
    rol = SelectField('Rol', choices=[('docente', 'Docente'), ('alumno', 'Alumno')], validators=[DataRequired()])
    submit = SubmitField('Registrarse')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    contraseña = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')

class CasoDePruebaForm(FlaskForm):
    descripcion = StringField('Descripción (Opcional)', validators=[Optional(), Length(max=255)])
    argumentos = TextAreaField(
        'Argumentos de Línea de Comandos (JSON Lista, Opcional)',
        validators=[Optional(), Length(max=2000), validate_json_list],
        render_kw={"placeholder": 'Ej: ["arg1", "arg2"] o ["10", "datos.txt"]', "style": "white-space: pre; font-family: monospace;"}
    )
    entrada = TextAreaField(
        'Entrada Estándar (Opcional)',
        validators=[Optional(), Length(max=5000)],
        render_kw={"placeholder": "Input que se pasará por STDIN", "style": "white-space: pre; font-family: monospace;"}
    )
    salida_esperada = TextAreaField(
        'Salida Esperada (Puede estar vacía)', 
        validators=[Optional(), Length(max=1000)],  # Cambiado a Optional()
        render_kw={"placeholder": "Salida EXACTA esperada en STDOUT", "style": "white-space: pre; font-family: monospace;"}
    )
    puntos = FloatField('Puntos', validators=[DataRequired()])
    es_oculto = BooleanField('Caso Oculto', default=False)

class PreguntaForm(FlaskForm):
    enunciado = TextAreaField('Enunciado de la Pregunta', validators=[DataRequired(), Length(max=10000)])
    puntaje_total = FloatField('Puntaje Total', validators=[DataRequired()])
    lenguaje_programacion = SelectField('Lenguaje de Programación', choices=LENGUAJES_SOPORTADOS, validators=[DataRequired()])
    linter_perfil = SelectField(
        'Herramienta/Perfil de Formato',
        choices=[('', '--- Ninguno ---')], # Choices se poblarán en la ruta/template
        validators=[Optional()], # Es opcional seleccionar un linter
        description="Selecciona el linter a aplicar (si el análisis de formato está habilitado para el examen)."
    )
    linter_args_adicionales = TextAreaField(
        'Argumentos Adicionales para Linter (Opcional)',
        validators=[Optional(), Length(max=500)], # Limitar longitud
        render_kw={
            "placeholder": "Ej: --ignore=E501 W503 --max-complexity=15",
            "rows": 2,
            "style": "font-family: monospace; font-size: 0.9em;"
        },
        description="Argumentos extra pasados al linter. Usar con precaución."
    )
    rubrica_evaluacion = TextAreaField(
        'Rúbrica de Evaluación (JSON, Opcional)',
        validators=[Optional(), validate_json_syntax], # Opcional y debe ser JSON si se ingresa
        render_kw={
            "placeholder": '{\n  "claridad_codigo": {\n    "descripcion": "Evaluar si el código es fácil de entender.",\n    "max_puntos": 2\n  },\n  "eficiencia": {\n    "descripcion": "Evaluar uso de algoritmos eficientes.",\n    "max_puntos": 3\n  },\n  "manejo_errores": {\n    "descripcion": "Evaluar si maneja casos borde.",\n    "max_puntos": 1\n  }\n}',
            "rows": 8, # Ajusta las filas según necesites
            "style": "font-family: monospace; font-size: 0.9em;" # Monospace ayuda a ver JSON
        },
        description="Define los criterios y puntajes en formato JSON que usará el LLM para evaluar esta pregunta."
    )
    casos_de_prueba = FieldList(FormField(CasoDePruebaForm), min_entries=0, max_entries=10)
 
class CrearExamenForm(FlaskForm):
    titulo = StringField('Título del Examen', validators=[DataRequired(), Length(max=200)])
    descripcion = TextAreaField('Descripción', validators=[Length(max=1000)])
    fecha_cierre = DateTimeField(
        'Fecha y Hora de Cierre',
        validators=[DataRequired(message="La fecha de cierre es obligatoria.")],
        format='%Y-%m-%dT%H:%M'  # Especifica el formato esperado de datetime-local
    )
    cursos = SelectMultipleField('Cursos', coerce=int, validators=[DataRequired()], render_kw={"multiple": True})
    preguntas = FieldList(FormField(PreguntaForm), min_entries=0)

    # Campos para la configuración del examen según lo definido en el modelo
    habilitar_formato = BooleanField('Habilitar análisis de formato', default=True)
    habilitar_metricas = BooleanField('Habilitar análisis de métricas', default=True)
    habilitar_similitud = BooleanField('Habilitar análisis de similitud', default=True)
    habilitar_rendimiento = BooleanField('Habilitar análisis de rendimiento', default=False)

    submit = SubmitField('Guardar Examen')

class EditarExamenForm(FlaskForm):
    titulo = StringField('Título del Examen', validators=[DataRequired(), Length(max=200)])
    descripcion = TextAreaField('Descripción', validators=[DataRequired(), Length(max=1000)])
    fecha_cierre = DateTimeField(
        'Fecha y Hora de Cierre',
        validators=[DataRequired(message="La fecha de cierre es obligatoria.")],
        format='%Y-%m-%dT%H:%M'  # Especifica el formato esperado de datetime-local
    )
    # No se incluye el campo de cursos
    preguntas = FieldList(FormField(PreguntaForm), min_entries=0)

    # Campos para la configuración del examen (habilitar o no funcionalidades)
    habilitar_formato = BooleanField('Habilitar análisis de formato')
    habilitar_metricas = BooleanField('Habilitar análisis de métricas')
    habilitar_similitud = BooleanField('Habilitar análisis de similitud')
    habilitar_rendimiento = BooleanField('Habilitar análisis de rendimiento')

    submit = SubmitField('Actualizar Examen')

class EntregaForm(FlaskForm):
    codigo_fuente = TextAreaField('Código Fuente', validators=[DataRequired(), Length(max=10000)])
    archivo = FileField('Subir Archivo', validators=[
        FileAllowed(['c', 'cpp', 'py', 'java', 'txt'], 'Solo se permiten archivos de código (c, cpp, py, java, txt).')
    ])
    submit = SubmitField('Enviar')
    
class DeleteForm(FlaskForm):
    submit = SubmitField('Eliminar')

class DummyForm(FlaskForm):
    pass  # This is an empty form to handle CSRF token if needed