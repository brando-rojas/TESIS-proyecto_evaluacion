
"""
Evaluador - Sistema de evaluación automática de entregas de código
"""

import subprocess
import tempfile
import os
import sys
import shlex
import time
import logging
from datetime import datetime, timezone
from difflib import unified_diff
from typing import Optional, Dict, Any, List, Tuple

# --- Importaciones de Modelos ---
from models import (
    Evaluacion, ResultadoDeEvaluacion, db, CasoDePrueba, Pregunta,
    Entrega, AnalisisResultado, HerramientaAnalisis,
    ConfiguracionExamen, TipoAnalisis
)

# --- Importar desde analysis_tools ---
try:
    from analysis_tools import (
        run_format_analysis_configurable,
        run_metrics_analysis,  # Import new metrics function
        run_complete_analysis  # Import combined analysis function
    )
except ImportError:
    logging.error("FATAL: No se pudo importar 'analysis_tools.py'. Las funciones de análisis no estarán disponibles.")
    def run_format_analysis_configurable(*args, **kwargs) -> Optional[Dict[str, Any]]:
        logging.warning("Usando función dummy para run_format_analysis_configurable debido a error de importación.")
        return None
    def run_metrics_analysis(*args, **kwargs) -> Optional[Dict[str, Any]]:
        logging.warning("Usando función dummy para run_metrics_analysis debido a error de importación.")
        return None
    def run_complete_analysis(*args, **kwargs) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        logging.warning("Usando función dummy para run_complete_analysis debido a error de importación.")
        return None, None, "Error: Módulo de análisis no disponible"

# --- Configuración, Constantes ---
ESTADO_EVALUANDO = 'evaluando'
ESTADO_COMPLETADA = 'completada'
ESTADO_ERROR = 'error'

# --- Configuración de logging ---
log = logging.getLogger(__name__)
if not log.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)  # O DEBUG

# --- Constantes de configuración ---
DEFAULT_TIMEOUT_SEC = 120  # Segundos para cada caso de prueba
DEFAULT_MAX_DIFF_LINES = 20  # Líneas máximas a mostrar en diferencias

# =========================================================
# === Funciones de Utilidad ===
# =========================================================

def normalize_line_endings(text: Optional[str]) -> str:
    """Normaliza los finales de línea a \\n."""
    if text is None:
        return ""
    return text.replace('\r\n', '\n').replace('\r', '\n')


def normalize_output(output: Optional[str]) -> str:
    """Normaliza finales de línea para comparación."""
    return normalize_line_endings(output)


def generar_resumen_diferencias(esperado: str, obtenido: str, max_lineas: int = DEFAULT_MAX_DIFF_LINES) -> Optional[str]:
    """Genera resumen de diferencias usando unified_diff."""
    esperado_norm = normalize_line_endings(esperado)
    obtenido_norm = normalize_line_endings(obtenido)

    if esperado_norm == obtenido_norm:
        if esperado != obtenido:
            return f"Diferencias menores detectadas (posiblemente espacios). Representación:\nEsperado: {repr(esperado)}\nObtenido: {repr(obtenido)}"
        else:
            return None

    esperado_lines = esperado_norm.splitlines()
    obtenido_lines = obtenido_norm.splitlines()

    diff = list(unified_diff(
        esperado_lines, obtenido_lines, fromfile='Esperado', tofile='Obtenido', lineterm=''
    ))

    if not diff:
        return f"Diferencias detectadas pero no mostradas por diff. Representación:\nEsperado: {repr(esperado)}\nObtenido: {repr(obtenido)}"

    resumen = '\n'.join(diff[:max_lineas])
    if len(diff) > max_lineas:
        resumen += f"\n... (Diferencias truncadas a {max_lineas} líneas)"
    return resumen


def get_herramienta_id(nombre_herramienta: str) -> Optional[int]:
    """Busca el ID de una herramienta de análisis en la BD por su nombre interno."""
    try:
        herramienta = HerramientaAnalisis.query.filter_by(nombre=nombre_herramienta).first()
        if herramienta:
            return herramienta.id
        else:
            log.warning(f"No se encontró la herramienta '{nombre_herramienta}' en la base de datos.")
            return None
    except Exception as e:
        log.error(f"Error buscando herramienta '{nombre_herramienta}' en la BD: {e}")
        return None


def obtener_sufijo_archivo(lenguaje: str) -> str:
    """Determina la extensión de archivo correcta según el lenguaje."""
    extensiones = {
        'python': '.py',
        'c': '.c',
        'java': '.java',
        'pseint': '.psc',
    }
    
    if lenguaje.lower() in extensiones:
        return extensiones[lenguaje.lower()]
    
    # Usar '.tmp' como fallback si el lenguaje es inesperado
    log.warning(f"Usando sufijo genérico '.tmp' para lenguaje desconocido: {lenguaje}")
    return '.tmp'


def limpiar_archivos_temporales(source_file_path: Optional[str], ejecutable_path: Optional[str], lenguaje: Optional[str]) -> None:
    """Limpia los archivos temporales creados durante la evaluación."""
    if source_file_path and os.path.exists(source_file_path):
        try:
            os.remove(source_file_path)
            log.info(f'Archivo fuente temporal eliminado: {source_file_path}')
        except OSError as e:
            log.error(f"Error eliminando archivo fuente temporal {source_file_path}: {e}")
    
    # Evitar borrar el fuente si es el mismo que el ejecutable (Python, PSeInt)
    if (ejecutable_path and os.path.exists(ejecutable_path) and 
        ejecutable_path != source_file_path and lenguaje == 'c'):
        try:
            os.remove(ejecutable_path)
            log.info(f'Ejecutable C eliminado: {ejecutable_path}')
        except OSError as e:
            log.error(f"Error eliminando ejecutable {ejecutable_path}: {e}")

# =========================================================
# === Funciones de Evaluación ===
# =========================================================

def ejecutar_caso_prueba(caso: CasoDePrueba, base_command: List[str], timeout_sec: int) -> ResultadoDeEvaluacion:
    """Ejecuta un único caso de prueba y devuelve el objeto ResultadoDeEvaluacion."""
    args_list = caso.obtener_argumentos()
    stdin_input = normalize_line_endings(caso.entrada if caso.entrada is not None else "")
    salida_esperada_original = caso.salida_esperada if caso.salida_esperada is not None else ""
    salida_esperada_norm = normalize_line_endings(salida_esperada_original)

    stdout_obtenido, stderr_obtenido = "", ""
    tiempo_inicio = time.monotonic()
    estado_ejecucion = "preparando"
    codigo_retorno = None
    diferencias_resumen = None
    paso_total = False
    tiempo_ejecucion_ms = None

    try:
        final_command = base_command + args_list
        log.info(f'Ejecutando caso {caso.id} (Desc: {caso.descripcion}): {" ".join(map(shlex.quote, final_command))}')
        if stdin_input: 
            log.debug(f'  -> Stdin: {repr(stdin_input[:100])}...')

        estado_ejecucion = "ejecutando"
        execute_process = subprocess.run(
            final_command,
            input=stdin_input,
            capture_output=True,
            timeout=timeout_sec,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        tiempo_fin = time.monotonic()
        tiempo_ejecucion_ms = int((tiempo_fin - tiempo_inicio) * 1000)
        codigo_retorno = execute_process.returncode
        estado_ejecucion = "completado" if codigo_retorno == 0 else f"error_exitcode_{codigo_retorno}"

        stdout_obtenido = execute_process.stdout
        stderr_obtenido = execute_process.stderr

        stdout_obtenido_norm = normalize_line_endings(stdout_obtenido)
        paso_total = (stdout_obtenido_norm == salida_esperada_norm)

        if codigo_retorno != 0 and stderr_obtenido:
            log.warning(f"Caso {caso.id} tuvo error en stderr (código {codigo_retorno}): {stderr_obtenido[:200]}...")
            # paso_total = False # Descomentar si error en stderr siempre debe fallar el caso

        if not paso_total:
            diferencias_resumen = generar_resumen_diferencias(salida_esperada_norm, stdout_obtenido_norm)

        log_level = logging.INFO if paso_total else logging.WARNING
        log.log(log_level, f'Caso {caso.id} {"OK" if paso_total else "Falló"} ({tiempo_ejecucion_ms} ms)')

    except subprocess.TimeoutExpired:
        tiempo_fin = time.monotonic()
        tiempo_ejecucion_ms = int((tiempo_fin - tiempo_inicio) * 1000)
        estado_ejecucion = "timeout"
        log.warning(f'Timeout ({timeout_sec}s) caso {caso.id}.')
        stdout_obtenido = "<TIMEOUT>"
        paso_total = False
    except Exception as e:
        tiempo_fin = time.monotonic()
        tiempo_ejecucion_ms = int((tiempo_fin - tiempo_inicio) * 1000) if tiempo_inicio else None
        estado_ejecucion = "error_interno_eval"
        error_msg = f"Error interno evaluador: {type(e).__name__}"
        log.error(f'Excepción caso {caso.id}: {e}', exc_info=True)
        stdout_obtenido = f"<ERROR INTERNO EVALUADOR: {e}>"
        stderr_obtenido = str(e)
        paso_total = False

    # Crear objeto resultado
    resultado_db = ResultadoDeEvaluacion(
        paso=paso_total,
        salida_obtenida=stdout_obtenido,
        puntos_obtenidos=caso.puntos if paso_total else 0.0,
        caso_de_prueba_id=caso.id,
        salida_obtenida_repr=repr(stdout_obtenido),
        salida_esperada_repr=repr(salida_esperada_original),
        entrada_repr=repr(caso.entrada) if caso.entrada else None,
        argumentos_repr=repr(args_list),
        stderr_obtenido=stderr_obtenido,
        stderr_obtenido_repr=repr(stderr_obtenido) if stderr_obtenido else None,
        tiempo_ejecucion_ms=tiempo_ejecucion_ms,
        estado_ejecucion=estado_ejecucion,
        codigo_retorno=codigo_retorno,
        diferencias_resumen=diferencias_resumen,
        fecha_ejecucion=datetime.now(timezone.utc)
    )
    return resultado_db


def compilar_codigo(source_file_path: str, lenguaje: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Compila el código según el lenguaje y devuelve una tupla con:
    (ejecutable_path, error_compilation, base_command)
    """
    ejecutable_path = None
    compile_error_output = None
    base_execute_command = []
    
    try:
        if lenguaje == 'c':
            base_name = os.path.splitext(source_file_path)[0]
            ejecutable_path = base_name + ('.exe' if sys.platform == 'win32' else '')
            compile_command = ['gcc', '-Wall', '-Wextra', '-std=c11', source_file_path, '-o', ejecutable_path, '-lm']
            log.info(f'Compilando C: {" ".join(map(shlex.quote, compile_command))}')
            compile_process = subprocess.run(compile_command, capture_output=True, text=True)
            if compile_process.returncode != 0:
                compile_error_output = f"Error de compilación:\n{compile_process.stderr}"
            else:
                base_execute_command = [ejecutable_path]
        
        elif lenguaje == 'python':
            python_cmd = sys.executable or 'python3'
            base_execute_command = [python_cmd, source_file_path]
            ejecutable_path = source_file_path
        
        elif lenguaje == 'java':
            base_name = os.path.splitext(source_file_path)[0]
            compile_command = ['javac', source_file_path]
            log.info(f'Compilando Java: {" ".join(map(shlex.quote, compile_command))}')
            compile_process = subprocess.run(compile_command, capture_output=True, text=True)
            if compile_process.returncode != 0:
                compile_error_output = f"Error de compilación:\n{compile_process.stderr}"
            else:
                base_execute_command = ['java', '-cp', os.path.dirname(source_file_path), os.path.basename(base_name)]
                ejecutable_path = base_name + '.class'
        
        else:
            compile_error_output = f"Error: Lenguaje '{lenguaje}' no soportado para ejecución."
            log.error(compile_error_output)

    except Exception as e:
        log.error(f"Error durante compilación: {e}", exc_info=True)
        compile_error_output = f"Error en compilación: {e}"
    
    return ejecutable_path, compile_error_output, base_execute_command


def ejecutar_analisis_formato(codigo_fuente: str, lenguaje: str, 
                              config_formato: Dict[str, Any]) -> Tuple[Optional[AnalisisResultado], Optional[str]]:
    """
    Ejecuta análisis de formato en el código y devuelve una tupla con:
    (objeto_analisis_db, feedback_str)
    """
    analisis_db = None
    feedback_str = None
    
    if not run_format_analysis_configurable:
        return None, "--- Análisis de Formato ---\n(Error interno: Módulo de análisis no disponible)"
    
    if not config_formato or 'perfil' not in config_formato:
        return None, "--- Análisis de Formato ---\n(No configurado correctamente para esta pregunta)"
    
    log.info(f"Ejecutando análisis de formato configurable...")
    resultado_formato = run_format_analysis_configurable(
        codigo_fuente, lenguaje, config_formato
    )
    
    if not resultado_formato:
        perfil_nom = config_formato.get('perfil', 'desconocido')
        return None, f"--- Análisis de Formato ---\n(No aplicable para perfil '{perfil_nom}' / lenguaje '{lenguaje}')"
    
    herramienta_id = get_herramienta_id(resultado_formato["tool_name"])
    if herramienta_id:
        analisis_db = AnalisisResultado(
            entrega_id=None,  # Se asignará después
            herramienta_id=herramienta_id,
            informe=resultado_formato["report"],
            puntuacion=1.0 if resultado_formato["success"] else 0.0,
            fecha_analisis=datetime.now(timezone.utc)
        )
    
    # Generar feedback
    tool_name_display = resultado_formato["tool_name"]
    if herramienta_id:
        herr_db = HerramientaAnalisis.query.get(herramienta_id)
        if herr_db and herr_db.nombre_mostrado: 
            tool_name_display = herr_db.nombre_mostrado

    feedback_str = f"--- Análisis de Formato ({tool_name_display}) ---\n"
    
    if resultado_formato["error"]:
        feedback_str += f"Error de la herramienta: {resultado_formato['error']}"
    elif not resultado_formato["success"]:
        reporte_truncado = resultado_formato['report']
        if len(reporte_truncado) > 1000:
            reporte_truncado = reporte_truncado[:1000] + "\n... (reporte truncado)"
        feedback_str += f"Se encontraron problemas:\n{reporte_truncado}"
    else:
        feedback_str += resultado_formato["report"]  # Mensaje de éxito
        
    return analisis_db, feedback_str

def ejecutar_analisis_metricas(codigo_fuente: str, lenguaje: str) -> Tuple[Optional[AnalisisResultado], Optional[str]]:
    """
    Ejecuta análisis de métricas en el código y devuelve una tupla con:
    (objeto_analisis_db, feedback_str)
    """
    analisis_db = None
    feedback_str = None
    
    if not run_metrics_analysis:
        return None, "--- Análisis de Métricas ---\n(Error interno: Módulo de análisis no disponible)"
    
    log.info(f"Ejecutando análisis de métricas para lenguaje {lenguaje}...")
    resultado_metricas = run_metrics_analysis(codigo_fuente, lenguaje)
    
    if not resultado_metricas:
        return None, f"--- Análisis de Métricas ---\n(No aplicable para lenguaje '{lenguaje}')"
    
    herramienta_id = get_herramienta_id(resultado_metricas["tool_name"])
    if herramienta_id:
        analisis_db = AnalisisResultado(
            entrega_id=None,  # Se asignará después
            herramienta_id=herramienta_id,
            informe=resultado_metricas["report"],
            puntuacion=1.0,  # Métricas no tienen éxito/fracaso, solo informan
            fecha_analisis=datetime.now(timezone.utc)
        )
    
    # Generar feedback
    tool_name_display = resultado_metricas["tool_name"]
    if herramienta_id:
        herr_db = HerramientaAnalisis.query.get(herramienta_id)
        if herr_db and herr_db.nombre_mostrado: 
            tool_name_display = herr_db.nombre_mostrado

    feedback_str = resultado_metricas["report"]
        
    return analisis_db, feedback_str

def generar_feedback_casos(resultados: List[ResultadoDeEvaluacion]) -> str:
    """Genera feedback de los resultados de casos de prueba."""
    if not resultados:
        return "--- Pruebas Funcionales ---\n(No hay resultados de casos de prueba)"
    
    casos_pasados = sum(1 for r in resultados if r.paso)
    casos_totales = len(resultados)
    fb_casos = [f"--- Pruebas Funcionales ---",
                f"Resumen Casos Prueba: {casos_pasados} de {casos_totales} pasaron."]
    
    if any(not r.paso for r in resultados):
        fb_casos.append("\nDetalles Casos Fallidos:")
        for idx, res in enumerate(resultados):
            if not res.paso:
                caso_desc = f"Caso {idx+1}"
                if hasattr(res, 'caso_de_prueba') and res.caso_de_prueba and res.caso_de_prueba.descripcion:
                    caso_desc = f"Caso {idx+1}: {res.caso_de_prueba.descripcion}"
                
                estado = "Falló"
                if res.estado_ejecucion == "timeout":
                    estado = "Timeout"
                elif res.estado_ejecucion.startswith("error_"):
                    estado = "Error"
                
                fb_casos.append(f"- {caso_desc}: {estado}")
                if res.diferencias_resumen:
                    fb_casos.append(f"  Diferencias:\n  {res.diferencias_resumen.replace('\n', '\n  ')}")
    
    return "\n".join(fb_casos)


def guardar_evaluacion_y_resultados(
    evaluacion: Evaluacion, 
    analisis_resultados: List[Optional[AnalisisResultado]],
    resultados_casos: List[ResultadoDeEvaluacion]
) -> bool:
    """Guarda todos los resultados de la evaluación en la base de datos de forma transaccional."""
    try:
        log.debug("Iniciando transacción para guardar resultados...")
        with db.session.begin_nested():
            if evaluacion not in db.session:
                db.session.add(evaluacion)

            log.debug(f"Eliminando resultados previos (si existen) para entrega {evaluacion.entrega_id}...")
            # Usar el ID de la entrega para borrar análisis, ya que pueden existir sin evaluación previa
            AnalisisResultado.query.filter_by(entrega_id=evaluacion.entrega_id).delete()
            # Si la evaluación ya tenía ID, borrar sus resultados antiguos
            if evaluacion.id:
                ResultadoDeEvaluacion.query.filter_by(evaluacion_id=evaluacion.id).delete()
            db.session.flush()  # Aplicar deletes

            # Añadir nuevos resultados
            for analisis in analisis_resultados:
                if analisis:
                    log.debug(f"Añadiendo AnalisisResultado...")
                    analisis.entrega_id = evaluacion.entrega_id
                    db.session.add(analisis)

            if resultados_casos:
                log.debug(f"Añadiendo {len(resultados_casos)} ResultadoDeEvaluacion...")
                db.session.flush()  # Asegurar que evaluacion tenga ID
                evaluacion_id_actual = evaluacion.id
                if not evaluacion_id_actual:
                    log.error("¡FALLO CRÍTICO! No se pudo obtener ID de evaluación después de flush.")
                    raise ValueError("ID de evaluación no disponible.")
                
                for res_caso in resultados_casos:
                    res_caso.evaluacion_id = evaluacion_id_actual
                    db.session.add(res_caso)

        db.session.commit()  # Commit de la transacción principal
        log.info(f"Evaluación {evaluacion.id} y resultados asociados guardados exitosamente.")
        return True

    except Exception as e:
        db.session.rollback()
        log.error(f"Error guardando resultados: {e}", exc_info=True)
        return False

def guardar_evaluacion_error(entrega_id: int, mensaje_error: str) -> bool:
    """Guarda una evaluación con mensaje de error."""
    try:
        evaluacion_error = Evaluacion.query.filter_by(entrega_id=entrega_id).first()
        if not evaluacion_error:
            evaluacion_error = Evaluacion(entrega_id=entrega_id)
        
        evaluacion_error.puntaje_obtenido = 0.0
        evaluacion_error.feedback = mensaje_error
        evaluacion_error.fecha_evaluacion = datetime.now(timezone.utc)
        
        if evaluacion_error not in db.session:
            db.session.add(evaluacion_error)
        
        db.session.commit()
        log.warning("Se guardó la evaluación con un mensaje de error.")
        return True
    
    except Exception as e:
        db.session.rollback()
        log.critical(f"FALLÓ al guardar la evaluación de error: {e}")
        return False

# =========================================================
# === Función Principal de Evaluación ===
# =========================================================

def evaluar_entrega(entrega: Entrega):
    """
    Evalúa una entrega: ejecuta análisis de formato y métricas (si están configurados) y casos de prueba.
    Guarda los resultados en la base de datos.
    """
    if not entrega:
        log.error("evaluar_entrega llamada con entrega None.")
        return

    # Validar que existe pregunta y examen
    pregunta: Pregunta = entrega.pregunta
    if not pregunta:
        log.error(f"No se encontró la pregunta para la entrega {entrega.id}.")
        return
    
    examen = pregunta.examen
    if not examen:
        log.error(f"No se encontró el examen para la pregunta {pregunta.id} (entrega {entrega.id}).")
        return

    # Obtener configuraciones
    config_examen = examen.configuracion_examen
    habilitar_formato = getattr(config_examen, 'habilitar_formato', False)
    habilitar_metricas = getattr(config_examen, 'habilitar_metricas', False)
    habilitar_similitud = getattr(config_examen, 'habilitar_similitud', False)
    habilitar_rendimiento = getattr(config_examen, 'habilitar_rendimiento', False)
    
    # Datos principales
    casos_de_prueba = pregunta.casos_de_prueba
    lenguaje = pregunta.lenguaje_programacion.lower() if pregunta.lenguaje_programacion else None
    codigo_fuente = entrega.codigo_fuente

    # Variables de resultados
    source_file_path = None
    ejecutable_path = None
    analisis_resultados = []  # Lista para todos los análisis
    resultados_casos_db = []
    total_puntos_casos = 0.0
    estado_evaluacion = ESTADO_COMPLETADA
    
    # Componentes de feedback
    feedback_formato = None
    feedback_metricas = None
    feedback_casos = None
    feedback_consolidado = None

    try:
        log.info(f"Iniciando evaluación para entrega {entrega.id} (Pregunta {pregunta.id}, Examen {examen.id})")

        # 1. Validación Inicial
        if not codigo_fuente:
            log.warning(f"Entrega {entrega.id} no tiene código fuente. Saltando análisis y ejecución.")
            feedback_formato = "--- Análisis de Formato ---\n(No se proporcionó código)"
            feedback_metricas = "--- Análisis de Métricas ---\n(No se proporcionó código)"
            feedback_casos = "--- Pruebas Funcionales ---\n(No se proporcionó código)"
            estado_evaluacion = ESTADO_ERROR
            raise ValueError("No se proporcionó código fuente en la entrega")

        if not lenguaje:
            log.error(f"Pregunta {pregunta.id} no tiene lenguaje definido. No se puede evaluar.")
            estado_evaluacion = ESTADO_ERROR
            raise ValueError(f"No se especificó lenguaje para la pregunta {pregunta.id}")

        # 2. Analisis combinado de formato y métricas cuando ambos están habilitados
        if habilitar_formato and habilitar_metricas:
            config_formato_pregunta = pregunta.obtener_configuracion_formato() if habilitar_formato else None
            
            log.info(f"Ejecutando análisis combinado de formato y métricas...")
            formato_results, metrics_results, consolidated_report = run_complete_analysis(
                codigo_fuente, lenguaje, config_formato_pregunta
            )
            
            # Procesar resultados de formato si están disponibles
            if formato_results:
                herramienta_id = get_herramienta_id(formato_results["tool_name"])
                if herramienta_id:
                    analisis_formato = AnalisisResultado(
                        entrega_id=None,  # Se asignará después
                        herramienta_id=herramienta_id,
                        informe=formato_results["report"],
                        puntuacion=1.0 if formato_results["success"] else 0.0,
                        fecha_analisis=datetime.now(timezone.utc)
                    )
                    analisis_resultados.append(analisis_formato)
                feedback_formato = formato_results["report"]
            
            # Procesar resultados de métricas si están disponibles
            if metrics_results:
                herramienta_id = get_herramienta_id(metrics_results["tool_name"])
                if herramienta_id:
                    analisis_metrica = AnalisisResultado(
                        entrega_id=None,  # Se asignará después
                        herramienta_id=herramienta_id,
                        informe=metrics_results["report"],
                        puntuacion=1.0,  # Métricas no tienen éxito/fracaso
                        fecha_analisis=datetime.now(timezone.utc)
                    )
                    analisis_resultados.append(analisis_metrica)
                feedback_metricas = metrics_results["report"]
            
            # Usar el reporte consolidado si está disponible
            if consolidated_report:
                feedback_consolidado = consolidated_report
                
        # 3. Análisis individuales si solo uno está habilitado
        else:
            # Análisis de Formato (solo)
            if habilitar_formato:
                config_formato_pregunta = pregunta.obtener_configuracion_formato()
                if config_formato_pregunta:
                    analisis_formato, feedback_formato = ejecutar_analisis_formato(
                        codigo_fuente, lenguaje, config_formato_pregunta
                    )
                    if analisis_formato:
                        analisis_resultados.append(analisis_formato)
                else:
                    log.info(f"Análisis formato habilitado pero no configurado para Pregunta {pregunta.id}")
                    feedback_formato = "--- Análisis de Formato ---\n(No configurado para esta pregunta)"
            else:
                log.info(f"Análisis de formato deshabilitado globalmente para examen {examen.id}")
                feedback_formato = "--- Análisis de Formato ---\n(Deshabilitado para este examen)"

            # Análisis de Métricas (solo)
            if habilitar_metricas:
                analisis_metrica, feedback_metricas = ejecutar_analisis_metricas(
                    codigo_fuente, lenguaje
                )
                if analisis_metrica:
                    analisis_resultados.append(analisis_metrica)
            else:
                log.info(f"Análisis de métricas deshabilitado globalmente para examen {examen.id}")
                feedback_metricas = "--- Análisis de Métricas ---\n(Deshabilitado para este examen)"

        # 4. Preparación y Compilación para casos de prueba
        try:
            # Crear archivo temporal con el código
            suffix = obtener_sufijo_archivo(lenguaje)
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='w',
                                            encoding='utf-8', newline='\n') as source_file:
                source_file.write(codigo_fuente)
                source_file_path = source_file.name
            log.info(f'Archivo temporal creado: {source_file_path}')
            
            # Compilar o preparar según el lenguaje
            ejecutable_path, compile_error, base_execute_command = compilar_codigo(source_file_path, lenguaje)
            
            if compile_error:
                estado_evaluacion = ESTADO_ERROR
                feedback_casos = f"--- Compilación y Pruebas Funcionales ---\n{compile_error}"
                raise ValueError(f"Error de compilación: {compile_error}")
                
        except Exception as e:
            log.error(f"Error durante preparación/compilación: {e}", exc_info=True)
            if not feedback_casos:  # Si no se asignó en el bloque try
                feedback_casos = f"--- Compilación y Pruebas Funcionales ---\nError: {e}"
            estado_evaluacion = ESTADO_ERROR
            raise

        # 5. Ejecución de Casos de Prueba
        if base_execute_command:  # Si hay comando y no hubo error previo
            log.info(f"Iniciando ejecución de {len(casos_de_prueba)} casos de prueba...")
            
            if casos_de_prueba:
                for caso in casos_de_prueba:
                    resultado_caso = ejecutar_caso_prueba(caso, base_execute_command, DEFAULT_TIMEOUT_SEC)
                    resultados_casos_db.append(resultado_caso)
                    total_puntos_casos += resultado_caso.puntos_obtenidos
                
                # Generar feedback de casos
                feedback_casos = generar_feedback_casos(resultados_casos_db)
            else:
                log.warning(f"No hay casos de prueba definidos para pregunta {pregunta.id}")
                feedback_casos = "--- Pruebas Funcionales ---\n(No hay casos de prueba definidos)"
        
        # 6. Combinar Feedback y Guardar Evaluación
        log.info("Combinando feedback y preparando para guardar...")
        
        # Si tenemos un reporte consolidado, usarlo como base y añadir los casos
        if feedback_consolidado:
            feedback_parts = [feedback_consolidado, feedback_casos]
        else:
            feedback_parts = [feedback_formato, feedback_metricas, feedback_casos]
            
        feedback_final = "\n\n".join(filter(None, feedback_parts)).strip()
        
        if not feedback_final:
            feedback_final = "(Evaluación completada, sin feedback adicional generado)"

        # Crear o actualizar evaluación
        evaluacion = Evaluacion.query.filter_by(entrega_id=entrega.id).first()
        if not evaluacion:
            log.info(f"Creando nueva evaluación para entrega {entrega.id}")
            evaluacion = Evaluacion(entrega_id=entrega.id)
        else:
            log.info(f"Actualizando evaluación existente {evaluacion.id} para entrega {entrega.id}")

        evaluacion.puntaje_obtenido = round(total_puntos_casos, 2)
        evaluacion.feedback = feedback_final
        evaluacion.fecha_evaluacion = datetime.now(timezone.utc)

        # Guardar todos los resultados
        guardado_ok = guardar_evaluacion_y_resultados(
            evaluacion, analisis_resultados, resultados_casos_db
        )
        
        if not guardado_ok:
            estado_evaluacion = ESTADO_ERROR
            # Intentar guardar al menos la evaluación con mensaje de error
            error_info = f"\n\n--- ERROR AL GUARDAR RESULTADOS ---"
            feedback_final += error_info
            guardar_evaluacion_error(entrega.id, feedback_final)

    except Exception as e:
        log.error(f'Error durante evaluación de entrega {entrega.id}: {e}', exc_info=True)
        estado_evaluacion = ESTADO_ERROR
        
        # Asegurar que tenemos feedback para la evaluación
        feedback_error = f"--- ERROR CRÍTICO DEL EVALUADOR ---\n{type(e).__name__}: {e}"
        guardar_evaluacion_error(entrega.id, feedback_error)
        
    finally:
        # Siempre limpiar archivos temporales
        limpiar_archivos_temporales(source_file_path, ejecutable_path, lenguaje)
        
        log.info(f"Evaluación finalizada para entrega {entrega.id}. Estado: {estado_evaluacion}. Puntaje: {total_puntos_casos}")
        return estado_evaluacion
