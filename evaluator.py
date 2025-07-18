
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
import json
import re

# --- Importaciones de Modelos ---
from models import (
    Evaluacion, ResultadoDeEvaluacion, db, CasoDePrueba, Pregunta,
    Entrega, AnalisisResultado, HerramientaAnalisis,
    ConfiguracionExamen, TipoAnalisis, ResultadoCriterioLLM 
)

import openai

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
else:
    logging.warning("OPENAI_API_KEY no encontrada en las variables de entorno. El análisis con LLM no funcionará.")

LLM_MODEL_OPENAI = "gpt-3.5-turbo-0125"

def construir_prompt_llm(enunciado: str, codigo_estudiante: str, rubrica_json_str: str, solucion_modelo: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Construye el prompt en formato de mensajes para la API de Chat de OpenAI.
    Ahora la rúbrica se pasa como string para incluirla directamente en el prompt del sistema.
    """
    system_message_content = f"""
Eres un asistente de profesor experto y justo, especializado en evaluar código de programación de estudiantes.
Tu tarea es analizar el código proporcionado por un estudiante en respuesta a un problema específico y evaluarlo
rigurosamente según una rúbrica dada.

**Instrucciones Generales:**
1.  Lee cuidadosamente el enunciado del problema, el código del estudiante, y (si se proporciona) la solución modelo.
2.  Evalúa el código del estudiante basándote ÚNICAMENTE en los criterios definidos en la RÚBRICA JSON proporcionada.
3.  Para cada criterio en la rúbrica, asigna un puntaje numérico. Este puntaje no debe exceder el 'max_puntaje' especificado para ese criterio en la rúbrica. El puntaje mínimo es 0.
4.  Proporciona una justificación breve y constructiva para el puntaje asignado a cada criterio.
5.  Adicionalmente, escribe un feedback general conciso sobre la solución del estudiante.
6.  Tu respuesta DEBE ser un objeto JSON válido. No incluyas ningún texto antes o después del objeto JSON.

**Formato de Salida JSON Requerido:**
El objeto JSON raíz debe tener una clave "evaluacion_llm". El valor de esta clave debe ser otro objeto con las siguientes dos claves:
  - "feedback_general": (string) Un resumen cualitativo general de la solución del estudiante (máximo 150 palabras).
  - "resultados_criterios": (array de objetos) Cada objeto en el array representa un criterio evaluado y debe contener:
    - "criterio_nombre": (string) El nombre exacto del criterio como aparece en la rúbrica.
    - "puntaje_obtenido": (number) Tu puntaje numérico para este criterio.
    - "max_puntaje_criterio": (number) El puntaje máximo para este criterio, tal como se define en la rúbrica.
    - "feedback_criterio": (string) Tu justificación detallada para el puntaje otorgado a este criterio (máximo 100 palabras por criterio).

A continuación, se proporcionará el enunciado, la rúbrica, la solución modelo (si existe) y el código del estudiante.
---
RÚBRICA DE EVALUACIÓN (JSON):
{rubrica_json_str}
---
"""
    user_message_content_parts = [
        f"ENUNCIADO DEL PROBLEMA:\n{enunciado}\n---"
    ]
    if solucion_modelo:
        user_message_content_parts.append(f"SOLUCIÓN MODELO (Referencia):\n{solucion_modelo}\n---")
    
    user_message_content_parts.append(f"CÓDIGO DEL ESTUDIANTE A EVALUAR:\n```\n{codigo_estudiante}\n```\n---")
    user_message_content_parts.append("Por favor, proporciona tu evaluación en el formato JSON especificado anteriormente.")

    user_message_content = "\n".join(user_message_content_parts)

    return [
        {"role": "system", "content": system_message_content.strip()},
        {"role": "user", "content": user_message_content.strip()}
    ]


def llamar_api_openai_llm(messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Llama a la API de Chat de OpenAI y retorna el contenido de 'evaluacion_llm'."""
    if not OPENAI_API_KEY:
        log.error("OPENAI_API_KEY no configurada. Saltando análisis LLM.")
        return None
    
    try:
        log.info(f"Enviando solicitud a la API de OpenAI (modelo: {LLM_MODEL_OPENAI})...")
        client = openai.OpenAI() # La API key se toma de la variable de entorno por defecto
        response = client.chat.completions.create(
            model=LLM_MODEL_OPENAI,
            messages=messages,
            temperature=0.2,  # Más bajo para mayor consistencia en evaluación
            # max_tokens=1500, # Ajustar según necesidad, pero el modelo puede manejarlo
            response_format={"type": "json_object"} # Solicitar explícitamente salida JSON
        )
        
        contenido_respuesta = response.choices[0].message.content

        # ———> Imprimir el contenido crudo para depuración <———
        print("=== Respuesta cruda LLM ===")
        print(contenido_respuesta)
        print("============================\n")
        
        if not contenido_respuesta:
            log.error("Respuesta del LLM de OpenAI vacía.")
            return None

        # Intentar parsear el contenido como JSON
        try:
            evaluacion_completa = json.loads(contenido_respuesta)
            if "evaluacion_llm" in evaluacion_completa:
                 log.info("Respuesta JSON del LLM recibida y parseada correctamente.")
                 return evaluacion_completa["evaluacion_llm"] 
            else:
                log.error(f"Respuesta JSON del LLM no contiene la clave 'evaluacion_llm'. Respuesta: {contenido_respuesta}")
                return None
        except json.JSONDecodeError as e:
            log.error(f"No se pudo decodificar la respuesta del LLM como JSON. Error: {e}. Respuesta: {contenido_respuesta}")
            return None

    except openai.APIError as e:
        log.error(f"Error en la API de OpenAI: {e}")
        return None
    except Exception as e:
        log.error(f"Error inesperado al procesar respuesta del LLM de OpenAI: {e}", exc_info=True)
        return None
    
def ejecutar_analisis_llm(entrega: Entrega, pregunta: Pregunta) -> Tuple[Optional[List[ResultadoCriterioLLM]], Optional[str], float]:
    """
    Ejecuta el análisis con LLM de OpenAI para una entrega.
    Retorna: (lista_resultados_criterios_db, feedback_general_llm, puntaje_total_llm)
    """
    codigo_estudiante = entrega.codigo_fuente
    enunciado = pregunta.enunciado
    rubrica_json_str = pregunta.rubrica_evaluacion # Asumimos que es un string JSON
    solucion_modelo = pregunta.solucion_modelo

    lista_resultados_db = []
    feedback_general_txt = None
    puntaje_total_llm = 0.0

    if not rubrica_json_str:
        log.warning(f"Pregunta {pregunta.id} no tiene rúbrica definida para análisis LLM. Saltando.")
        return None, "Análisis con IA no realizado: Rúbrica no definida.", 0.0

    # Intentar parsear la rúbrica para validación y para extraer max_puntaje
    try:
        rubrica_dict = json.loads(rubrica_json_str)
        if not isinstance(rubrica_dict.get("criterios"), list):
            raise ValueError("'criterios' debe ser una lista en la rúbrica.")
        for crit_rubrica in rubrica_dict["criterios"]:
            if not all(k in crit_rubrica for k in ["nombre", "descripcion_general", "max_puntaje_criterio"]):
                raise ValueError("Cada criterio en la rúbrica debe tener 'nombre', 'descripcion_general', y 'max_puntaje_criterio'.")
            if not isinstance(crit_rubrica["max_puntaje_criterio"], (int, float)) or crit_rubrica["max_puntaje_criterio"] < 0:
                raise ValueError("'max_puntaje_criterio' debe ser un número no negativo.")

    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Formato de rúbrica JSON inválido para Pregunta {pregunta.id}: {e}. Rúbrica: {rubrica_json_str}")
        return None, f"Análisis con IA no realizado: Formato de rúbrica inválido ({e}).", 0.0


    messages_prompt = construir_prompt_llm(enunciado, codigo_estudiante, rubrica_json_str, solucion_modelo)
    # log.debug(f"Prompt para LLM (Pregunta {pregunta.id}):\n{json.dumps(messages_prompt, indent=2)}")

    resultado_api_llm = llamar_api_openai_llm(messages_prompt)

    # ———> Mostrar el JSON ya parseado para que lo veas antes de armar feedback_general_txt
    if resultado_api_llm is not None:
        import json as _json
        print("=== JSON LLM parseado ===")
        print(_json.dumps(resultado_api_llm, indent=2, ensure_ascii=False))
        print("==========================\n")

    if resultado_api_llm:
        feedback_general_txt = resultado_api_llm.get("feedback_general")
        resultados_criterios_api = resultado_api_llm.get("resultados_criterios", [])

        if isinstance(resultados_criterios_api, list):
            for criterio_api in resultados_criterios_api:
                nombre = criterio_api.get("criterio_nombre")
                puntaje_obtenido_api = criterio_api.get("puntaje_obtenido")
                # El LLM ahora también debería devolver max_puntaje_criterio según el prompt
                max_puntaje_api = criterio_api.get("max_puntaje_criterio")
                feedback_crit = criterio_api.get("feedback_criterio")
                
                if nombre is not None and puntaje_obtenido_api is not None and max_puntaje_api is not None:
                    try:
                        puntaje_float = float(puntaje_obtenido_api)
                        max_puntaje_float = float(max_puntaje_api)

                        # Validación y ajuste del puntaje
                        if puntaje_float > max_puntaje_float:
                            log.warning(f"Puntaje LLM ({puntaje_float}) para '{nombre}' excede max_puntaje_criterio ({max_puntaje_float}). Ajustando a {max_puntaje_float}.")
                            puntaje_float = max_puntaje_float
                        if puntaje_float < 0:
                            log.warning(f"Puntaje LLM ({puntaje_float}) para '{nombre}' es negativo. Ajustando a 0.")
                            puntaje_float = 0.0

                        resultado_db = ResultadoCriterioLLM(
                            criterio_nombre=str(nombre),
                            puntaje_obtenido_llm=puntaje_float,
                            max_puntaje_criterio=max_puntaje_float,
                            feedback_criterio_llm=str(feedback_crit) if feedback_crit else None
                        )
                        lista_resultados_db.append(resultado_db)
                        puntaje_total_llm += puntaje_float
                    except ValueError:
                        log.error(f"Puntaje LLM o max_puntaje_criterio para criterio '{nombre}' no son números válidos: {puntaje_obtenido_api}, {max_puntaje_api}")
                else:
                    log.warning(f"Resultado de criterio LLM incompleto (faltan claves requeridas): {criterio_api}")
        else:
            log.error(f"La clave 'resultados_criterios' del LLM no es una lista: {resultados_criterios_api}")
            feedback_general_txt = (feedback_general_txt or "") + "\nError: La IA no pudo procesar los criterios de la rúbrica correctamente."
    else:
        feedback_general_txt = "Error durante el análisis con IA. No se pudo obtener una evaluación detallada de los criterios."

    return lista_resultados_db, feedback_general_txt, round(puntaje_total_llm, 2)

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
    log.setLevel(logging.DEBUG)  # O DEBUG

# --- Constantes de configuración ---
DEFAULT_TIMEOUT_SEC = 120  # Segundos para cada caso de prueba
DEFAULT_MAX_DIFF_LINES = 20  # Líneas máximas a mostrar en diferencias

# =========================================================
# === Funciones de Utilidad ===
# =========================================================

def normalize_output_flexibly(text: Optional[str]) -> str:
    """
    Normaliza una cadena de texto de forma flexible para la comparación.
    1. Convierte todos los finales de línea a \n.
    2. Elimina espacios en blanco y tabulaciones al principio y final de CADA LÍNEA.
    3. Reemplaza secuencias de múltiples espacios/tabulaciones con un solo espacio.
    4. Ignora mayúsculas y minúsculas.
    5. Normaliza la representación de números de punto flotante.
    """
    if text is None:
        return ""
    
    # 1. Normalizar saltos de línea y quitar espacios al inicio/final del texto completo
    normalized_text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    
    # 2. Procesar cada línea individualmente
    lines = normalized_text.split('\n')
    processed_lines = []
    for line in lines:
        # 3. Quitar espacios al inicio/final de la línea y reducir espacios intermedios
        line = re.sub(r'\s+', ' ', line.strip())
        
        # 4. Normalizar números flotantes en la línea
        # Busca patrones como "x: -1.2345", "y: 3.14" o simplemente números
        # y los redondea a un número fijo de decimales (ej. 4)
        def round_match(match):
            try:
                # El grupo 0 es el match completo
                number = float(match.group(0))
                return f"{number:.4f}" # Redondear a 4 decimales
            except (ValueError, IndexError):
                return match.group(0) # Si no es un número, devolverlo como está

        # Expresión regular para encontrar números flotantes (posiblemente negativos)
        line = re.sub(r'-?\d+\.\d+', round_match, line)
        
        processed_lines.append(line)
        
    # 5. Unir las líneas procesadas y convertir todo a minúsculas
    return '\n'.join(processed_lines).lower()



def generar_resumen_diferencias(esperado: str, obtenido: str, max_lineas: int = DEFAULT_MAX_DIFF_LINES) -> Optional[str]:
    """Genera resumen de diferencias usando unified_diff."""
    esperado_norm = normalize_output_flexibly(esperado)
    obtenido_norm = normalize_output_flexibly(obtenido)

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
    stdin_input = normalize_output_flexibly(caso.entrada if caso.entrada is not None else "")
    salida_esperada_original = caso.salida_esperada if caso.salida_esperada is not None else ""
    
    # --- LOG INICIAL DE DATOS DEL CASO ---
    log.debug(f"--- INICIO CASO {caso.id} ---")
    log.debug(f"Caso ID: {caso.id}, Descripción: {caso.descripcion}")
    log.debug(f"Argumentos: {args_list}")
    log.debug(f"Entrada STDIN Original (repr): {repr(caso.entrada)}")
    log.debug(f"Entrada STDIN Normalizada (repr): {repr(stdin_input)}")
    log.debug(f"Salida Esperada Original (repr): {repr(salida_esperada_original)}")
    
    salida_esperada_norm = normalize_output_flexibly(salida_esperada_original).strip() # <--- AÑADIR .strip() AQUÍ
    log.debug(f"Salida Esperada Normalizada y Stripped (repr): {repr(salida_esperada_norm)}")
    # --- FIN LOG INICIAL ---

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
            log.debug(f'  -> Stdin a enviar: {repr(stdin_input)}') # Mostrar exactamente lo que se envía

        estado_ejecucion = "ejecutando"
        execute_process = subprocess.run(
            final_command,
            input=stdin_input,
            capture_output=True,
            timeout=timeout_sec,
            text=True, # Importante para decodificar a string
            encoding='utf-8', # Especificar encoding
            errors='replace'  # Reemplazar caracteres inválidos en la decodificación
        )
        tiempo_fin = time.monotonic()
        tiempo_ejecucion_ms = int((tiempo_fin - tiempo_inicio) * 1000)
        codigo_retorno = execute_process.returncode
        estado_ejecucion = "completado" if codigo_retorno == 0 else f"error_exitcode_{codigo_retorno}"

        stdout_obtenido = execute_process.stdout
        stderr_obtenido = execute_process.stderr

        # --- LOG DE SALIDAS OBTENIDAS ---
        log.debug(f"--- SALIDAS OBTENIDAS CASO {caso.id} ---")
        log.debug(f"STDOUT Original (repr): {repr(stdout_obtenido)}")
        log.debug(f"STDERR Original (repr): {repr(stderr_obtenido)}")

        stdout_obtenido_norm = normalize_output_flexibly(stdout_obtenido).strip() # <--- AÑADIR .strip() AQUÍ
        log.debug(f"STDOUT Normalizado y Stripped (repr): {repr(stdout_obtenido_norm)}")
        # --- FIN LOG SALIDAS ---

        # --- COMPARACIÓN ---
        paso_total = (stdout_obtenido_norm == salida_esperada_norm)
        log.debug(f"Comparación: stdout_obtenido_norm == salida_esperada_norm -> {paso_total}")
        if not paso_total:
            log.warning(f"FALLO EN COMPARACIÓN para Caso {caso.id}:")
            log.warning(f"  Esperado (norm+strip, repr): {repr(salida_esperada_norm)}")
            log_multiline_string("  Obtenido (norm+strip, repr):", repr(stdout_obtenido_norm)) # Para ver saltos de línea como \n
            log_multiline_string("  Obtenido (norm+strip, literal):", stdout_obtenido_norm) # Para ver cómo se ve
            # También es útil ver los bytes para detectar caracteres invisibles
            log.warning(f"  Esperado (bytes): {salida_esperada_norm.encode('utf-8', 'replace')}")
            log.warning(f"  Obtenido (bytes): {stdout_obtenido_norm.encode('utf-8', 'replace')}")


        if codigo_retorno != 0 and stderr_obtenido:
            log.warning(f"Caso {caso.id} tuvo error en stderr (código {codigo_retorno}): {stderr_obtenido[:200]}...")
            # Si un error en stderr debe hacer fallar el caso aunque el stdout coincida:
            # if paso_total: # Si había pasado por stdout pero hay error en stderr
            #     log.warning(f"Caso {caso.id} pasó por STDOUT pero falló por STDERR no vacío.")
            #     paso_total = False 

        if not paso_total: # Volver a generar diferencias si paso_total es False
            diferencias_resumen = generar_resumen_diferencias(salida_esperada_norm, stdout_obtenido_norm)
            if diferencias_resumen:
                log.warning(f"Resumen de Diferencias Caso {caso.id}:\n{diferencias_resumen}")
            else:
                log.warning(f"Caso {caso.id} falló pero generar_resumen_diferencias no encontró diferencias visuales (podría ser espacios finales o caracteres invisibles).")


        log_level = logging.INFO if paso_total else logging.WARNING
        log.log(log_level, f'Resultado final Caso {caso.id}: {"OK" if paso_total else "Falló"} ({tiempo_ejecucion_ms} ms)')

    except subprocess.TimeoutExpired:
        # ... (tu manejo de Timeout sin cambios) ...
        tiempo_fin = time.monotonic()
        tiempo_ejecucion_ms = int((tiempo_fin - tiempo_inicio) * 1000)
        estado_ejecucion = "timeout"
        log.warning(f'Timeout ({timeout_sec}s) caso {caso.id}.')
        stdout_obtenido = "<TIMEOUT>"
        paso_total = False
    except Exception as e:
        # ... (tu manejo de Exception sin cambios) ...
        tiempo_fin = time.monotonic()
        tiempo_ejecucion_ms = int((tiempo_fin - tiempo_inicio) * 1000) if tiempo_inicio else None
        estado_ejecucion = "error_interno_eval"
        log.error(f'Excepción caso {caso.id}: {e}', exc_info=True)
        stdout_obtenido = f"<ERROR INTERNO EVALUADOR: {e}>"
        stderr_obtenido = str(e)
        paso_total = False

    # Crear objeto resultado
    resultado_db = ResultadoDeEvaluacion(
        paso=paso_total,
        salida_obtenida=stdout_obtenido, # Guardar el stdout original
        puntos_obtenidos=caso.puntos if paso_total else 0.0,
        caso_de_prueba_id=caso.id,
        salida_obtenida_repr=repr(stdout_obtenido), # repr del original
        salida_esperada_repr=repr(salida_esperada_original), # repr del original
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

# Nueva función de utilidad para loggear strings multilínea
def log_multiline_string(prefix: str, content: str):
    """Loggea un string que puede tener múltiples líneas, añadiendo un prefijo a cada línea."""
    for i, line_content in enumerate(content.splitlines()):
        log.warning(f"{prefix} (línea {i+1}): {line_content}")
    if not content.splitlines(): # Si es una cadena vacía o solo espacios sin saltos de línea
        log.warning(f"{prefix} (vacío o solo espacios): {repr(content)}")


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
    resultados_casos: List[ResultadoDeEvaluacion],
    resultados_llm: Optional[List[ResultadoCriterioLLM]] # Añadido
) -> bool:
    # ... (se mantiene igual, pero con el nuevo parámetro resultados_llm) ...
    try:
        with db.session.begin_nested():
            if evaluacion not in db.session: db.session.add(evaluacion)
            AnalisisResultado.query.filter_by(entrega_id=evaluacion.entrega_id).delete()
            if evaluacion.id:
                ResultadoDeEvaluacion.query.filter_by(evaluacion_id=evaluacion.id).delete()
                ResultadoCriterioLLM.query.filter_by(evaluacion_id=evaluacion.id).delete() # Limpiar previos
            db.session.flush()
            for analisis in analisis_resultados:
                if analisis: analisis.entrega_id = evaluacion.entrega_id; db.session.add(analisis)
            eval_id = evaluacion.id or db.session.execute(db.select(Evaluacion.id).filter_by(entrega_id=evaluacion.entrega_id)).scalar_one() # Obtener ID
            if not eval_id: raise ValueError("ID de evaluación no disponible")
            evaluacion.id = eval_id # Asegurar que el objeto tenga el ID
            for res_caso in resultados_casos: res_caso.evaluacion_id = eval_id; db.session.add(res_caso)
            if resultados_llm:
                for res_llm in resultados_llm: res_llm.evaluacion_id = eval_id; db.session.add(res_llm)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback(); log.error(f"Error guardando resultados: {e}", exc_info=True); return False

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
    
    habilitar_analisis_llm = getattr(config_examen, 'habilitar_analisis_llm', True)

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
    
    resultados_criterios_llm_db: Optional[List[ResultadoCriterioLLM]] = None
    puntaje_llm_obtenido = 0.0

    # Componentes de feedback
    feedback_formato = None
    feedback_metricas = None
    feedback_casos = None
    feedback_consolidado = None

    resultados_criterios_llm_db: Optional[List[ResultadoCriterioLLM]] = None # Inicializar
    
    total_puntos_casos = 0.0
    puntaje_llm_obtenido = 0.0 # INICIALIZAR
    estado_evaluacion = ESTADO_COMPLETADA # Asumir éxito inicial
    
    feedback_formato: Optional[str] = None
    feedback_metricas: Optional[str] = None
    feedback_casos: Optional[str] = None
    feedback_llm_general_txt: Optional[str] = None # INICIALIZAR
    feedback_llm_criterios_str_list: List[str] = [] # INICIALIZAR como lista vacía

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
        
        # 3.5 Análisis con LLM
        if habilitar_analisis_llm and pregunta.rubrica_evaluacion:
            log.info(f"Ejecutando análisis con LLM para entrega {entrega.id}...")
            resultados_criterios_llm_db, feedback_llm_general_txt, puntaje_llm_obtenido = ejecutar_analisis_llm(entrega, pregunta)

            if resultados_criterios_llm_db: # Si hubo resultados de criterios
                feedback_llm_criterios_str_list.append("\n--- Evaluación Cualitativa (IA) ---")
                if feedback_llm_general_txt:
                    feedback_llm_criterios_str_list.append(f"Feedback General (IA): {feedback_llm_general_txt}")
                
                feedback_llm_criterios_str_list.append("Detalle por Criterio (IA):")
                for crit_res in resultados_criterios_llm_db:
                    max_p_str = f"/{crit_res.max_puntaje_criterio}" if crit_res.max_puntaje_criterio is not None else ""
                    fb_line = f"- {crit_res.criterio_nombre}: {crit_res.puntaje_obtenido_llm}{max_p_str} pts."
                    if crit_res.feedback_criterio_llm:
                        fb_line += f" (Feedback: {crit_res.feedback_criterio_llm})"
                    feedback_llm_criterios_str_list.append(fb_line)
                feedback_llm_criterios_str_list.append(f"Puntaje Total Cualitativo (IA): {puntaje_llm_obtenido} pts.")
            
            elif feedback_llm_general_txt: # Si SOLO hubo feedback general (quizás error en criterios)
                feedback_llm_criterios_str_list = ["\n--- Evaluación Cualitativa (IA) ---", feedback_llm_general_txt]
            # Si no hubo ni resultados ni feedback general, feedback_llm_general_txt sigue siendo None y feedback_llm_criterios_str_list vacía

        elif habilitar_analisis_llm: # Pero no hay rúbrica
             feedback_llm_criterios_str_list = ["\n--- Evaluación Cualitativa (IA) ---\n(Rúbrica no definida para esta pregunta)"]

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
        # Base con formato+métricas (sea consolidado o por separado)
        if feedback_consolidado:
            base_report = feedback_consolidado
        else:
            base_report = "\n\n".join(filter(None, [feedback_formato, feedback_metricas]))
            
        # Siempre añadimos los casos funcionales y la evaluación de IA
        feedback_parts = [
            base_report,
            feedback_casos,
            *feedback_llm_criterios_str_list
        ]
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
        evaluacion.feedback_llm_general = feedback_llm_general_txt # Guardar feedback general del LLM
        evaluacion.fecha_evaluacion = datetime.now(timezone.utc)

        if not guardar_evaluacion_y_resultados(evaluacion, analisis_resultados, resultados_casos_db, resultados_criterios_llm_db):
            estado_evaluacion = ESTADO_ERROR
            guardar_evaluacion_error(entrega.id, feedback_final + "\n\n--- ERROR AL GUARDAR RESULTADOS ---")

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
