# analysis_tools.py

import subprocess
import tempfile
import os
import logging
import json
import shlex # Para parsear argumentos de forma segura
import re
from typing import Dict, Any, Optional, Tuple, List # Añadir List

# Configuración básica de logging para este módulo
log = logging.getLogger(__name__)
# Es buena idea configurar el logger principal en tu app.py o __init__.py
# Si no, al menos configura un handler básico aquí para ver los logs de este módulo:
if not log.hasHandlers():
     handler = logging.StreamHandler() # Muestra logs en consola
     formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
     handler.setFormatter(formatter)
     log.addHandler(handler)
     log.setLevel(logging.INFO) # O logging.DEBUG para más detalle


# --- Constantes para Nombres Internos (deben coincidir con BD) ---
# Python
TOOL_FLAKE8 = "flake8"
TOOL_PYLINT = "pylint"
TOOL_BLACK_CHECK = "black-check"
# C/C++
TOOL_CLANG_FORMAT_GOOGLE = "clang-format-google"
TOOL_CLANG_FORMAT_LLVM = "clang-format-llvm"
TOOL_CLANG_FORMAT_WEBKIT = "clang-format-webkit"
# TOOL_CLANG_TIDY = "clang-tidy-default" # Si lo implementas

LANGUAGE_TO_SUFFIX = {
    'python': ['.py'],
    'c': ['.c', '.h'],
    'cpp': ['.cpp', '.cxx', '.h', '.hpp'],
    'java': ['.java'],
    'pseint': ['.psc'] # Si soportas pseint
    # Añade otros mapeos si es necesario
}

# --- Mapeo de Perfiles a Comandos y Argumentos Base ---
# Clave: nombre del perfil (como se guarda en la BD y se selecciona en el form)
# Valor: Diccionario con detalles de ejecución.
LINTER_PROFILES: Dict[str, Dict[str, Any]] = {
    # --- Perfiles Python ---
    TOOL_FLAKE8: {
        "command": ["flake8"],
        "base_args": ["--select=E,W", "--max-line-length=120", "--format=default", "--exit-zero"], # exit-zero evita que falle solo por issues
        "suffix": ".py",
        "success_on_empty_output": True # Flake8 éxito si stdout está vacío (con --exit-zero)
    },
    TOOL_PYLINT: {
        "command": ["pylint"],
        # Pylint puede necesitar un rcfile para ser útil. Si no, quitar --rcfile.
        # Puedes ajustar el nivel de error con --fail-under=<score>
        "base_args": ["--output-format=text"], # Ejemplo sin rcfile
        # "base_args": ["--output-format=text", "--rcfile=/path/to/sensible/pylintrc"],
        "suffix": ".py",
        # Pylint usa bits en el código de salida para diferentes tipos de mensajes.
        # 0 = sin errores/warnings. >0 indica problemas. Podríamos ser más específicos.
        "success_on_returncode": [0] # Considerar éxito solo si no hay mensajes (código 0)
    },
    TOOL_BLACK_CHECK: {
        "command": ["black"],
        "base_args": ["--check", "--diff"], # --check no modifica, --diff muestra qué cambiaría
        "suffix": ".py",
        "success_on_returncode": [0] # Black --check devuelve 0 si no se necesita formateo
    },

    # --- Perfiles C/C++ ---
    TOOL_CLANG_FORMAT_GOOGLE: {
        "command": ["clang-format"],
        # --dry-run -Werror: No modifica, pero falla (return code != 0) si se necesita formateo.
        "base_args": ["-style=google", "--dry-run", "-Werror"],
        "suffix": ".c", # Ajusta si necesitas .cpp, .h, etc.
        "success_on_returncode": [0] # Devuelve 0 si no hay cambios necesarios
    },
    TOOL_CLANG_FORMAT_LLVM: {
        "command": ["clang-format"],
        "base_args": ["-style=llvm", "--dry-run", "-Werror"],
        "suffix": ".c",
        "success_on_returncode": [0]
    },
    TOOL_CLANG_FORMAT_WEBKIT: {
        "command": ["clang-format"],
        "base_args": ["-style=webkit", "--dry-run", "-Werror"],
        "suffix": ".c",
        "success_on_returncode": [0]
    },
    # --- ClangTidy (Ejemplo - Requiere Configuración Adicional) ---
    # TOOL_CLANG_TIDY: {
    #     "command": ["clang-tidy"],
    #     # ¡MUY IMPORTANTE! ClangTidy necesita saber cómo compilar el código.
    #     # Esto usualmente se pasa después de '--'. La configuración base aquí es solo un ejemplo.
    #     "base_args": ["-checks=-*,readability-*,portability-*", "--warnings-as-errors=*"], # Habilita checks específicos, trata warnings como errores
    #     # Se necesitarían añadir los flags de compilación: ['--', '-std=c11', '-I/include/path']
    #     "suffix": ".c",
    #     "success_on_empty_output": True # Generalmente, sin salida significa sin problemas
    # }
}


def _run_linter_subprocess(
    profile_config: Dict[str, Any],
    extra_args_str: Optional[str],
    code: str,
    timeout: int = 30 # Segundos
) -> Tuple[bool, str, Optional[str]]:
    """
    Helper PRIVADO para ejecutar un linter en un subprocess con archivo temporal.

    Args:
        profile_config: Diccionario con la configuración del perfil del linter (de LINTER_PROFILES).
        extra_args_str: String con argumentos adicionales proporcionados por el usuario.
        code: El código fuente a analizar.
        timeout: Timeout en segundos para la ejecución del linter.

    Returns:
        Tuple: (success: bool, report: str, error_msg: Optional[str])
               success es True si el linter corrió y NO reportó issues (según criterios del perfil).
               report contiene la salida del linter (issues) o mensaje de éxito/error.
               error_msg contiene errores del propio linter, no del código analizado.
    """
    tmp_file_path: Optional[str] = None
    linter_name = profile_config.get("command", ["desconocido"])[0] # Nombre base del comando

    try:
        command_base: List[str] = list(profile_config["command"]) # Copiar lista
        base_args: List[str] = list(profile_config.get("base_args", [])) # Copiar lista
        suffix: str = profile_config["suffix"]

        # --- Parsear y añadir argumentos extra de forma segura ---
        final_extra_args: List[str] = []
        if extra_args_str:
            try:
                 # Permitir comentarios simples al final de la línea de args
                 safe_extra_args_str = re.sub(r'#.*', '', extra_args_str).strip()
                 if safe_extra_args_str:
                    parsed_args = shlex.split(safe_extra_args_str)
                    # --- Validación/Sanitización (IMPORTANTE EN PRODUCCIÓN) ---
                    # Aquí deberías añadir lógica para permitir solo argumentos seguros.
                    # EJEMPLO MUY BÁSICO: Rechazar argumentos que empiecen con '--output' o '-o'
                    #                 o que contengan '/' o '\' para evitar escrituras.
                    allowed_args = []
                    for arg in parsed_args:
                         if arg: # Ignorar vacíos
                              # Ejemplo muy simple de filtro:
                              # if arg.startswith(('--output', '-o')) or '/' in arg or '\\' in arg:
                              #      log.warning(f"Argumento adicional rechazado por seguridad: '{arg}'")
                              # else:
                              #      allowed_args.append(arg)
                              allowed_args.append(arg) # Por ahora, permitir (¡precaución!)
                    final_extra_args = allowed_args
                    log.info(f"Argumentos adicionales parseados para {linter_name}: {final_extra_args}")
            except ValueError as e_shlex:
                 # Error al parsear (ej. comillas sin cerrar)
                 err_msg = f"Error en formato de argumentos adicionales: {e_shlex}"
                 log.error(f"{err_msg} para linter {linter_name}. Args: '{extra_args_str}'")
                 # Devolver error claro al usuario/evaluador
                 return False, err_msg, f"Error shlex: {e_shlex}"

        # Combinar comando, args base, y args extra
        full_command = command_base + base_args + final_extra_args

        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8', newline='\n') as tmp_file:
            if code is None: code = "" # Asegurar que no sea None
            tmp_file.write(code)
            tmp_file_path = tmp_file.name

        # Añadir el path del archivo al final del comando (la mayoría de linters lo esperan así)
        full_command.append(tmp_file_path)

        log.info(f"Ejecutando linter: {' '.join(full_command)}")

        # Ejecutar el proceso
        process_result = subprocess.run(
            full_command,
            capture_output=True, # Capturar stdout y stderr
            text=True,           # Decodificar salida como texto
            encoding='utf-8',    # Especificar encoding
            errors='replace',    # Reemplazar caracteres inválidos
            timeout=timeout      # Establecer timeout
        )

        # --- Analizar Resultado basado en el perfil y la salida ---
        stdout = process_result.stdout.strip() if process_result.stdout else ""
        stderr = process_result.stderr.strip() if process_result.stderr else ""
        returncode = process_result.returncode

        log.debug(f"Linter {linter_name} stdout: {stdout[:500]}...") # Log truncado
        log.debug(f"Linter {linter_name} stderr: {stderr[:500]}...") # Log truncado
        log.debug(f"Linter {linter_name} returncode: {returncode}")

        # Determinar éxito y reporte
        report = ""
        error_msg = None # Error de la herramienta, no del código
        success = False

        # Criterios de éxito basados en la configuración del perfil
        if profile_config.get("success_on_empty_output", False):
            # Éxito si no hay salida relevante (stdout o stderr, según la herramienta)
            # Flake8 con --exit-zero escribe issues a stdout
            # ClangTidy escribe warnings/errores a stderr
            is_relevant_output = (linter_name == TOOL_FLAKE8 and stdout) or \
                                 (linter_name != TOOL_FLAKE8 and stderr and "warning:" in stderr.lower() or "error:" in stderr.lower())
                                 # Añadir más casos si es necesario

            if not is_relevant_output:
                 success = True
                 report = f"{linter_name}: No se encontraron problemas relevantes."
            else:
                 # Hubo salida, asumir que son issues reportados
                 report = stdout if linter_name == TOOL_FLAKE8 else stderr
                 # Verificar si stderr indica un error *de la herramienta* y no solo warnings del código
                 if stderr and ("error:" in stderr.lower() or "exception" in stderr.lower()) and linter_name != TOOL_FLAKE8:
                      error_msg = f"Error interno posible de {linter_name}: {stderr}"

        elif "success_on_returncode" in profile_config:
            # Éxito si el código de retorno está en la lista permitida
            if returncode in profile_config["success_on_returncode"]:
                 success = True
                 report = f"{linter_name}: Verificación completada sin problemas detectados."
                 # Algunos linters (black --check --diff) dan salida incluso en éxito
                 if stdout: report += f"\nSalida:\n{stdout}"
                 # if stderr: report += f"\nErrores/Warnings:\n{stderr}" # Mostrar stderr si lo hubo
            else:
                 # Falló según return code, el reporte es la salida principal
                 report = stdout if stdout else stderr # Mostrar stdout o stderr como reporte
                 # Verificar si stderr indica error de la herramienta
                 if stderr and ("error:" in stderr.lower() or "exception" in stderr.lower()):
                       error_msg = f"Error interno posible de {linter_name}: {stderr}"

        else: # Fallback si no se especificó criterio: éxito si returncode es 0
            if returncode == 0:
                 success = True
                 report = f"{linter_name}: Ejecución completada sin errores."
                 if stdout: report += f"\nSalida:\n{stdout}"
                 if stderr: report += f"\nErrores/Warnings:\n{stderr}"
            else:
                 report = stdout if stdout else stderr
                 if stderr and ("error:" in stderr.lower() or "exception" in stderr.lower()):
                       error_msg = f"Error interno posible de {linter_name}: {stderr}"

        # Limpiar paths del reporte si es necesario (hacerlo más robusto)
        if tmp_file_path:
             # Usar regex para reemplazar de forma más segura
             # Reemplazar /path/to/temp/file.py:lineno:col: con Linea lineno:col:
             report = re.sub(rf"{re.escape(tmp_file_path)}[:]?(\d+[:]?\d*[:]?\s*)", r"Linea \1", report)
             # Reemplazar cualquier otra ocurrencia del path completo
             report = report.replace(tmp_file_path, '[archivo]')

        log_level = logging.INFO if success else logging.WARNING
        log.log(log_level, f"Resultado linter {linter_name}: Success={success}. Reporte:\n{report[:500]}...")
        if error_msg: log.error(f"Error detectado en linter {linter_name}: {error_msg}")

        # Asegurar que el reporte no esté vacío si no hubo éxito
        if not success and not report.strip():
             report = f"{linter_name}: Se detectaron problemas (sin salida detallada)."

        return success, report.strip(), error_msg

    except FileNotFoundError:
        error_msg = f"Error: El comando '{linter_name}' no se encontró. Asegúrate de que esté instalado y en el PATH."
        log.error(error_msg)
        return False, error_msg, error_msg
    except subprocess.TimeoutExpired:
        error_msg = f"Error: Timeout ({timeout}s) ejecutando {linter_name}."
        log.warning(error_msg)
        return False, error_msg, error_msg
    except Exception as e:
        error_msg = f"Error inesperado ejecutando linter {linter_name}: {e}"
        log.exception(error_msg) # Incluir traceback en logs
        return False, error_msg, error_msg
    finally:
        # Limpieza del archivo temporal
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path)
                log.debug(f"Archivo temporal {tmp_file_path} eliminado.")
            except OSError as e_unlink:
                log.error(f"Error eliminando archivo temporal {tmp_file_path}: {e_unlink}")


# --- Función PÚBLICA para llamar desde evaluator.py ---
def run_format_analysis_configurable(
    code: str,
    language: str,
    config: Optional[Dict[str, Any]] # Recibe la config parseada de la pregunta
) -> Optional[Dict[str, Any]]:
    """
    Ejecuta el análisis de formato según la configuración de la pregunta.

    Args:
        code: Código fuente.
        language: Lenguaje ('python', 'c', etc.).
        config: Diccionario con la configuración parseada desde Pregunta.configuracion_formato_json.
                Debe contener al menos la clave 'perfil'.

    Returns:
        Diccionario con los resultados o None si no aplica/falla la configuración.
        {
            "tool_name": str,       # Nombre INTERNO del perfil/herramienta usada (ej: 'flake8')
            "success": bool,        # True si el linter corrió y no halló problemas
            "report": str,          # Salida/Reporte del linter o mensaje
            "error": Optional[str]  # Error del propio linter, no del código
        }
    """
    if not config or not isinstance(config, dict) or "perfil" not in config:
        log.info(f"Análisis de formato no configurado o perfil no especificado para pregunta asociada (lenguaje: {language}).")
        return None # No hay nada que hacer

    profile_name = config["perfil"]
    extra_args_str = config.get("args_adicionales", "") # Obtener args opcionales

    # Validar que el perfil exista en nuestra configuración
    if profile_name not in LINTER_PROFILES:
        err_msg = f"Error: Perfil de linter '{profile_name}' no reconocido en la configuración."
        log.error(err_msg)
        # Devolver un diccionario indicando el error de configuración
        return {"tool_name": profile_name, "success": False, "report": err_msg, "error": "Perfil no configurado"}

    profile_config = LINTER_PROFILES[profile_name]

    # Validar compatibilidad de lenguaje (doble check)
    language_code = language.lower()
    valid_suffixes_for_language = LANGUAGE_TO_SUFFIX.get(language_code, []) # Busca en el mapeo
    profile_suffix = profile_config.get("suffix", "").lower() # Obtiene el sufijo del perfil

    if not profile_suffix: # Error si el perfil no define sufijo
         err_msg = f"Error config: Perfil '{profile_name}' no tiene 'suffix'."
         log.error(err_msg)
         return {"tool_name": profile_name, "success": False, "report": err_msg, "error": "Configuración interna inválida"}

    # Verifica si el sufijo del perfil está DENTRO de la lista de sufijos válidos para el lenguaje
    if profile_suffix not in valid_suffixes_for_language:
         err_msg = f"Error: Perfil '{profile_name}' (para {profile_suffix}) no es aplicable para lenguaje '{language_code}' (sufijos válidos: {valid_suffixes_for_language})."
         log.error(err_msg)
         # Devuelve el error específico de incompatibilidad
         return {"tool_name": profile_name, "success": False, "report": err_msg, "error": "Incompatibilidad de lenguaje"}
    
    
    # Ejecutar el linter usando el helper
    success, report, error = _run_linter_subprocess(
        profile_config,
        extra_args_str,
        code
    )

    # Devolver el diccionario de resultados estructurado
    return {
        "tool_name": profile_name, # Nombre interno del perfil
        "success": success,
        "report": report,
        "error": error
    }

"""
Code Metrics Calculator

This module implements code metrics calculation for different programming languages
with a focus on readability and performance metrics. Each algorithm includes
analysis of its computational complexity.
"""

import ast
import re
from typing import Dict, Any, List, Set, Optional, Tuple


class PythonMetricVisitor(ast.NodeVisitor):
    """AST visitor to collect metrics from Python code.
    
    Time Complexity Analysis:
    - Overall: O(n) where n is the number of nodes in the AST
    - Each node is visited exactly once with constant-time operations
    """
    
    def __init__(self):
        self.line_count = 0
        self.func_line_counts = {}
        self.class_line_counts = {}
        self.complexity = {}
        self.imports = set()
        self.func_docstring_counts = {}
        self.class_count = 0
        self.function_count = 0
        self.method_count = 0
        self.comment_count = 0
        self.if_count = 0
        self.for_count = 0
        self.while_count = 0
        
    def visit_FunctionDef(self, node):
        """Visit function definitions to collect metrics.
        
        Time Complexity: O(m) where m is the number of nodes in the function
        """
        func_name = node.name
        # Calculate function line count
        start_line = node.lineno
        end_line = max(node.lineno, self._get_last_line(node))
        self.func_line_counts[func_name] = end_line - start_line + 1
        
        # Check docstring - O(1)
        if ast.get_docstring(node):
            self.func_docstring_counts[func_name] = True
        else:
            self.func_docstring_counts[func_name] = False
            
        # Calculate function complexity - O(m)
        complexity = 1  # Base complexity
        
        # Count branches to calculate McCabe complexity
        for subnode in ast.walk(node):  # O(m)
            if isinstance(subnode, (ast.If, ast.For, ast.While, ast.IfExp)):
                complexity += 1
                if isinstance(subnode, ast.If):
                    self.if_count += 1
                elif isinstance(subnode, ast.For):
                    self.for_count += 1
                elif isinstance(subnode, ast.While):
                    self.while_count += 1
            
            # Count boolean operations
            elif isinstance(subnode, ast.BoolOp):
                complexity += len(subnode.values) - 1
        
        self.complexity[func_name] = complexity
        
        # Check if this is a method or function - O(1)
        if self._is_method(node):
            self.method_count += 1
        else:
            self.function_count += 1
            
        self.generic_visit(node)
        
    def visit_ClassDef(self, node):
        """Visit class definitions to collect metrics.
        
        Time Complexity: O(k) where k is the number of nodes in the class
        """
        class_name = node.name
        # Calculate class line count
        start_line = node.lineno
        end_line = max(node.lineno, self._get_last_line(node))
        self.class_line_counts[class_name] = end_line - start_line + 1
        
        self.class_count += 1
        self.generic_visit(node)
        
    def visit_Import(self, node):
        """Track imports.
        
        Time Complexity: O(1) - constant time operation
        """
        for name in node.names:
            self.imports.add(name.name)
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        """Track from imports.
        
        Time Complexity: O(1) - constant time operation
        """
        if node.module:
            for name in node.names:
                if node.module == "__future__":
                    continue
                import_name = f"{node.module}.{name.name}"
                self.imports.add(import_name)
        self.generic_visit(node)
            
    def _get_last_line(self, node):
        """Get the last line number in a node.
        
        Time Complexity: O(p) where p is the number of child nodes
        """
        max_line = node.lineno
        for child_node in ast.iter_child_nodes(node):
            if hasattr(child_node, 'lineno'):
                max_line = max(max_line, child_node.lineno)
                max_line = max(max_line, self._get_last_line(child_node))
        return max_line
    
    def _is_method(self, node):
        """Check if a function definition is a method (inside a class).
        
        Time Complexity: O(1) - simplified implementation with constant time
        """
        # This is a simplified implementation
        # In practice, we would need to check node.parent or context
        return hasattr(node, 'parent') and isinstance(node.parent, ast.ClassDef)

    def estimate_total_lines(self, code):
        """Estimate total lines (including comments) from the raw code.
        
        Time Complexity: O(n) where n is the number of lines in the code
        """
        lines = code.split('\n')
        self.line_count = len(lines)
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                self.comment_count += 1


def calculate_python_metrics(code: str) -> Dict[str, Any]:
    """
    Calculate metrics for Python code.
    
    Time Complexity: O(n) where n is the size of the code
    - AST parsing: O(n)
    - AST traversal: O(n)
    - Final calculations: O(f) where f is the number of functions
    
    Args:
        code: Python source code
        
    Returns:
        Dict with metrics
    """
    try:
        # AST parsing - O(n)
        tree = ast.parse(code)
        visitor = PythonMetricVisitor()
        
        # AST traversal - O(n)
        visitor.visit(tree)
        visitor.estimate_total_lines(code)
        
        # Calculate additional summary metrics - O(f)
        funcs_with_docstring = sum(1 for has_doc in visitor.func_docstring_counts.values() if has_doc)
        total_funcs = len(visitor.func_docstring_counts)
        docstring_percentage = (funcs_with_docstring / total_funcs * 100) if total_funcs > 0 else 0
        
        avg_func_lines = sum(visitor.func_line_counts.values()) / len(visitor.func_line_counts) if visitor.func_line_counts else 0
        avg_complexity = sum(visitor.complexity.values()) / len(visitor.complexity) if visitor.complexity else 0
        max_complexity = max(visitor.complexity.values()) if visitor.complexity else 0
        complex_funcs = sum(1 for c in visitor.complexity.values() if c > 10)
        
        # Assembling final metrics - O(f)
        metrics = {
            "total_lines": visitor.line_count,
            "total_classes": visitor.class_count,
            "total_functions": visitor.function_count,
            "total_methods": visitor.method_count,
            "total_imports": len(visitor.imports),
            "comment_count": visitor.comment_count,
            "if_count": visitor.if_count,
            "for_count": visitor.for_count,
            "while_count": visitor.while_count,
            "docstring_percentage": round(docstring_percentage, 1),
            "avg_function_lines": round(avg_func_lines, 1),
            "avg_complexity": round(avg_complexity, 1),
            "max_complexity": max_complexity,
            "complex_functions": complex_funcs,
            "function_details": {
                func_name: {
                    "lines": visitor.func_line_counts[func_name],
                    "complexity": visitor.complexity.get(func_name, 1),
                    "has_docstring": visitor.func_docstring_counts.get(func_name, False)
                }
                for func_name in visitor.func_line_counts
            }
        }
        
        return metrics
    except SyntaxError as e:
        return {
            "error": f"Error de sintaxis en línea {e.lineno}, columna {e.offset}: {e.msg}"
        }
    except Exception as e:
        return {
            "error": f"Error analizando métricas: {str(e)}"
        }


def estimate_c_metrics(code: str) -> Dict[str, Any]:
    """
    Estimate metrics for C/C++ code using basic parsing.
    
    Time Complexity: O(n) where n is the number of lines in the code
    - Each line is processed once with regex operations
    
    Args:
        code: C/C++ source code
        
    Returns:
        Dict with metrics
    """
    metrics = {
        "total_lines": 0,
        "code_lines": 0,
        "comment_lines": 0,
        "blank_lines": 0,
        "function_count": 0,
        "if_count": 0,
        "for_count": 0,
        "while_count": 0,
        "switch_count": 0,
        "estimated_cyclomatic": 0,
        "include_count": 0,
        "preprocessor_count": 0,
        "function_details": {}
    }
    
    # Split into lines - O(n)
    lines = code.split('\n')
    metrics["total_lines"] = len(lines)
    
    # State tracking
    in_block_comment = False
    in_function = False
    current_function = ""
    function_start_line = 0
    function_braces = 0
    
    # Function pattern - simplified version 
    fn_pattern = re.compile(r'^\s*(?:static\s+)?(?:(?:unsigned|signed|struct|enum|const)\s+)?[a-zA-Z_][a-zA-Z0-9_]*\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*\)\s*{')
    
    # Process each line - O(n)
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Skip blank lines
        if not stripped:
            metrics["blank_lines"] += 1
            continue
            
        # Handle block comments
        if in_block_comment:
            metrics["comment_lines"] += 1
            if "*/" in line:
                in_block_comment = False
            continue
            
        # Check line/block comment start
        if stripped.startswith("//"):
            metrics["comment_lines"] += 1
            continue
        if "/*" in line:
            metrics["comment_lines"] += 1
            if "*/" not in line[line.find("/*") + 2:]:
                in_block_comment = True
            continue
            
        # Count code lines
        metrics["code_lines"] += 1
        
        # Check includes and preprocessor directives - O(1) operations
        if stripped.startswith("#include"):
            metrics["include_count"] += 1
        elif stripped.startswith("#"):
            metrics["preprocessor_count"] += 1
            
        # Count control structures - regex operations are effectively O(1) per line
        if re.search(r'\bif\s*\(', line):
            metrics["if_count"] += 1
            metrics["estimated_cyclomatic"] += 1
        if re.search(r'\bfor\s*\(', line):
            metrics["for_count"] += 1
            metrics["estimated_cyclomatic"] += 1
        if re.search(r'\bwhile\s*\(', line):
            metrics["while_count"] += 1
            metrics["estimated_cyclomatic"] += 1
        if re.search(r'\bswitch\s*\(', line):
            metrics["switch_count"] += 1
        if re.search(r'\bcase\s+', line):
            metrics["estimated_cyclomatic"] += 1
            
        # Try to detect function definitions - regex match is O(1) per line
        if not in_function:
            match = fn_pattern.match(line)
            if match:
                current_function = match.group(1)
                function_start_line = i + 1
                in_function = True
                function_braces = 1
                metrics["function_count"] += 1
                metrics["function_details"][current_function] = {
                    "start_line": function_start_line,
                    "complexity": 1  # Base complexity
                }
        
        # Track function complexity and end - O(1) operations
        if in_function:
            # Track braces to find function end
            function_details = metrics["function_details"][current_function]
            
            if "{" in line:
                function_braces += line.count("{")
            if "}" in line:
                function_braces -= line.count("}")
                
            # Increment complexity for control structures in this function
            if re.search(r'\bif\s*\(', line):
                function_details["complexity"] += 1
            if re.search(r'\bfor\s*\(', line):
                function_details["complexity"] += 1
            if re.search(r'\bwhile\s*\(', line):
                function_details["complexity"] += 1
            if re.search(r'\bcase\s+', line):
                function_details["complexity"] += 1
                
            # Check if function ends
            if function_braces == 0:
                in_function = False
                function_details["lines"] = (i + 1) - function_start_line
    
    return metrics


def calculate_generic_metrics(code: str) -> Dict[str, Any]:
    """
    Calculate basic metrics for any language.
    
    Time Complexity: O(n) where n is the number of lines in the code
    
    Args:
        code: Source code
        
    Returns:
        Dict with metrics
    """
    metrics = {
        "total_lines": 0,
        "non_empty_lines": 0,
        "avg_line_length": 0,
        "max_line_length": 0,
    }
    
    # Split code into lines - O(n)
    lines = code.split('\n')
    metrics["total_lines"] = len(lines)
    
    # Filter non-empty lines - O(n)
    non_empty_lines = [line for line in lines if line.strip()]
    metrics["non_empty_lines"] = len(non_empty_lines)
    
    # Calculate line length statistics - O(n)
    if non_empty_lines:
        line_lengths = [len(line) for line in non_empty_lines]
        metrics["avg_line_length"] = round(sum(line_lengths) / len(line_lengths), 1)
        metrics["max_line_length"] = max(line_lengths)
        
    return metrics


def calculate_metrics(code: str, language: str) -> Dict[str, Any]:
    """
    Calculate metrics for the provided code based on language.
    
    Time Complexity: 
    - O(n) where n is the size of the code
    - All underlying functions have linear time complexity
    
    Args:
        code: Source code
        language: Programming language ('python', 'c', 'java', etc.)
        
    Returns:
        Dict with metrics results
    """
    language = language.lower()
    
    # Get generic metrics for all languages - O(n)
    results = calculate_generic_metrics(code)
    results["language"] = language
    
    # Get language-specific metrics
    try:
        if language == 'python':
            # Python metrics - O(n)
            python_metrics = calculate_python_metrics(code)
            results.update(python_metrics)
        elif language in ['c', 'cpp', 'c++']:
            # C/C++ metrics - O(n)
            c_metrics = estimate_c_metrics(code)
            results.update(c_metrics)
    except Exception as e:
        results["error"] = f"Error calculando métricas específicas para {language}: {str(e)}"
    
    return results


def format_metrics_report(metrics: Dict[str, Any]) -> str:
    """
    Format metrics into a readable report.
    
    Time Complexity: O(f) where f is the number of functions in the code
    - Most operations are O(1)
    - The most expensive part is formatting function details which is O(f)
    
    Args:
        metrics: Dictionary of calculated metrics
        
    Returns:
        Formatted report string
    """
    if "error" in metrics:
        return f"Error en análisis de métricas: {metrics['error']}"
    
    lines = ["=== REPORTE DE MÉTRICAS ==="]
    
    # Basic metrics for all languages - O(1)
    lines.append(f"\n--- Métricas Básicas ({metrics.get('language', 'desconocido')}) ---")
    lines.append(f"Líneas totales: {metrics.get('total_lines', 0)}")
    lines.append(f"Líneas no vacías: {metrics.get('non_empty_lines', 0)}")
    lines.append(f"Longitud promedio por línea: {metrics.get('avg_line_length', 0)}")
    lines.append(f"Longitud máxima de línea: {metrics.get('max_line_length', 0)}")
    
    # Python-specific metrics - O(1) except for function details which is O(f)
    if metrics.get('language') == 'python' and 'total_functions' in metrics:
        lines.append("\n--- Métricas Estructura (Python) ---")
        lines.append(f"Clases: {metrics.get('total_classes', 0)}")
        lines.append(f"Funciones: {metrics.get('total_functions', 0)}")
        lines.append(f"Métodos: {metrics.get('total_methods', 0)}")
        lines.append(f"Imports: {metrics.get('total_imports', 0)}")
        lines.append(f"Comentarios: {metrics.get('comment_count', 0)}")
        
        lines.append("\n--- Métricas de Complejidad ---")
        lines.append(f"Complejidad ciclomática promedio: {metrics.get('avg_complexity', 0)}")
        lines.append(f"Complejidad máxima: {metrics.get('max_complexity', 0)}")
        lines.append(f"Funciones complejas (>10): {metrics.get('complex_functions', 0)}")
        lines.append(f"Porcentaje de funciones documentadas: {metrics.get('docstring_percentage', 0)}%")
        
        lines.append("\n--- Métricas de Control de Flujo ---")
        lines.append(f"Estructuras if/elif: {metrics.get('if_count', 0)}")
        lines.append(f"Bucles for: {metrics.get('for_count', 0)}")
        lines.append(f"Bucles while: {metrics.get('while_count', 0)}")
        
        # Add function details - O(f)
        function_details = metrics.get("function_details", {})
        if function_details and len(function_details) <= 10:
            lines.append("\n--- Detalle por Función ---")
            for func_name, details in function_details.items():
                doc_status = "Con" if details.get("has_docstring", False) else "Sin"
                lines.append(f"• {func_name}: {details.get('lines', 0)} líneas, " +
                          f"Complejidad: {details.get('complexity', 1)}, " +
                          f"{doc_status} docstring")
        elif function_details:
            lines.append("\n--- Funciones más complejas ---")
            # Get the 5 most complex functions - O(f log f) for sorting
            complex_funcs = sorted(
                function_details.items(),
                key=lambda x: x[1].get("complexity", 0),
                reverse=True
            )[:5]
            for func_name, details in complex_funcs:
                doc_status = "Con" if details.get("has_docstring", False) else "Sin"
                lines.append(f"• {func_name}: {details.get('lines', 0)} líneas, " +
                          f"Complejidad: {details.get('complexity', 1)}, " +
                          f"{doc_status} docstring")
    
    # C/C++ specific metrics - O(1) except for function details which is O(f) 
    elif metrics.get('language') in ['c', 'cpp', 'c++'] and 'function_count' in metrics:
        lines.append("\n--- Métricas Estructura (C/C++) ---")
        lines.append(f"Funciones: {metrics.get('function_count', 0)}")
        lines.append(f"Directivas #include: {metrics.get('include_count', 0)}")
        lines.append(f"Otras directivas #: {metrics.get('preprocessor_count', 0)}")
        lines.append(f"Líneas de código: {metrics.get('code_lines', 0)}")
        lines.append(f"Líneas de comentarios: {metrics.get('comment_lines', 0)}")
        
        lines.append("\n--- Métricas de Complejidad ---")
        lines.append(f"Complejidad ciclomática estimada: {metrics.get('estimated_cyclomatic', 0)}")
        
        lines.append("\n--- Métricas de Control de Flujo ---")
        lines.append(f"Estructuras if: {metrics.get('if_count', 0)}")
        lines.append(f"Bucles for: {metrics.get('for_count', 0)}")
        lines.append(f"Bucles while: {metrics.get('while_count', 0)}")
        lines.append(f"Estructuras switch: {metrics.get('switch_count', 0)}")
        
        # Add function details - O(f)
        function_details = metrics.get("function_details", {})
        if function_details and len(function_details) <= 10:
            lines.append("\n--- Detalle por Función ---")
            for func_name, details in function_details.items():
                lines.append(f"• {func_name}: {details.get('lines', 0)} líneas, " +
                          f"Complejidad: {details.get('complexity', 1)}")
    
    return "\n".join(lines)


def run_metrics_analysis(code: str, language: str) -> Dict[str, Any]:
    """
    Run metrics analysis on code.
    
    Time Complexity: O(n) where n is the size of the code
    - Calculate metrics: O(n)
    - Format report: O(f) where f is the number of functions
    - Since f < n, overall complexity is O(n)
    
    Args:
        code: Source code
        language: Programming language
        
    Returns:
        Dict with metric results including report
    """
    tool_name = "basic-metrics"
    
    try:
        # Calculate metrics - O(n)
        metrics = calculate_metrics(code, language)
        
        # Generate report - O(f)
        report = format_metrics_report(metrics)
        
        # Determine success
        success = "error" not in metrics
        error = metrics.get("error") if "error" in metrics else None
        
        return {
            "tool_name": tool_name,
            "success": success,
            "report": report,
            "error": error,
            "metrics": metrics
        }
    except Exception as e:
        return {
            "tool_name": tool_name,
            "success": False,
            "report": f"Error en análisis de métricas: {e}",
            "error": str(e),
            "metrics": {"error": str(e)}
        }


def generate_consolidated_report(
    format_results: Optional[Dict[str, Any]],
    metrics_results: Optional[Dict[str, Any]]
) -> str:
    """
    Generate a combined report from format and metrics analysis.
    
    Time Complexity: O(n) where n is the size of the metrics data
    - Processing format results: O(1)
    - Processing metrics results: O(f) where f is the number of functions
    - Generating recommendations: O(1)
    
    Args:
        format_results: Results from format analysis
        metrics_results: Results from metrics analysis
        
    Returns:
        Consolidated report as string
    """
    report_parts = []
    
    # Add header - O(1)
    report_parts.append("========================================")
    report_parts.append("      REPORTE DE ANÁLISIS DE CÓDIGO     ")
    report_parts.append("========================================")
    
    # Add format analysis section - O(1)
    report_parts.append("\n\n## ANÁLISIS DE FORMATO")
    
    if format_results:
        if format_results.get("success", False):
            report_parts.append("✅ Formato correcto")
        else:
            report_parts.append("❌ Problemas de formato detectados")
        
        # Add format report
        format_report = format_results.get("report", "")
        if format_report:
            report_parts.append("\nDetalles:")
            report_parts.append(format_report)
    else:
        report_parts.append("⚠️ Análisis de formato no realizado o no configurado")
    
    # Add metrics section - O(f)
    report_parts.append("\n\n## ANÁLISIS DE MÉTRICAS")
    
    if metrics_results:
        metrics = metrics_results.get("metrics", {})
        
        # Add complexity score with emoji indicator - O(1)
        complexity = calculate_cyclomatic_complexity(metrics)
        complexity_indicator = "🟢" if complexity < 8 else "🟡" if complexity < 15 else "🔴"
        
        language = metrics.get("language", "desconocido")
        report_parts.append(f"\nComplejidad ciclomática máxima: {complexity_indicator} {complexity}")
        
        # Add line count with emoji indicator - O(1)
        line_count = metrics.get("total_lines", 0)
        lines_indicator = "🟢" if line_count < 200 else "🟡" if line_count < 500 else "🔴"
        report_parts.append(f"Total de líneas: {lines_indicator} {line_count}")
        
        # Add Python-specific metrics - O(1)
        if language == "python":
            func_count = metrics.get("total_functions", 0) + metrics.get("total_methods", 0)
            func_indicator = "🟢" if func_count < 10 else "🟡" if func_count < 20 else "🔴"
            report_parts.append(f"Total de funciones/métodos: {func_indicator} {func_count}")
            
            docstring_pct = metrics.get("docstring_percentage", 0)
            doc_indicator = "🟢" if docstring_pct > 80 else "🟡" if docstring_pct > 50 else "🔴"
            report_parts.append(f"Documentación (docstrings): {doc_indicator} {docstring_pct}%")
        
        # Add C/C++ specific metrics - O(1)
        elif language in ["c", "cpp", "c++"]:
            func_count = metrics.get("function_count", 0)
            func_indicator = "🟢" if func_count < 10 else "🟡" if func_count < 20 else "🔴"
            report_parts.append(f"Total de funciones: {func_indicator} {func_count}")
            
            comment_ratio = metrics.get("comment_lines", 0) / max(metrics.get("code_lines", 1), 1) * 100
            comment_indicator = "🟢" if comment_ratio > 20 else "🟡" if comment_ratio > 10 else "🔴"
            report_parts.append(f"Ratio de comentarios: {comment_indicator} {round(comment_ratio, 1)}%")
        
        # Add full metrics report - O(f)
        metrics_report = metrics_results.get("report", "")
        if metrics_report:
            report_parts.append("\nDetalles:")
            report_parts.append(metrics_report)
    else:
        report_parts.append("⚠️ Análisis de métricas no realizado")
    
    # Add recommendations - O(1)
    report_parts.append("\n\n## RECOMENDACIONES")
    recommendations = []
    
    if format_results and not format_results.get("success", False):
        recommendations.append("• Corrige los problemas de formato indicados arriba.")
    
    if metrics_results:
        metrics = metrics_results.get("metrics", {})
        language = metrics.get("language", "")
        
        if language == "python":
            if metrics.get("docstring_percentage", 100) < 70:
                recommendations.append("• Mejora la documentación añadiendo docstrings a las funciones.")
            
            complex_funcs = metrics.get("complex_functions", 0)
            if complex_funcs > 0:
                recommendations.append(f"• Refactoriza las {complex_funcs} funciones complejas dividiéndolas en subfunciones.")
            
            max_line_len = metrics.get("max_line_length", 0)
            if max_line_len > 100:
                recommendations.append("• Mejora la legibilidad acortando las líneas muy largas.")
        
        elif language in ["c", "cpp", "c++"]:
            comment_ratio = metrics.get("comment_lines", 0) / max(metrics.get("code_lines", 1), 1) * 100
            if comment_ratio < 15:
                recommendations.append("• Añade más comentarios para explicar la lógica del código.")
            
            if metrics.get("estimated_cyclomatic", 0) > 10:
                recommendations.append("• Refactoriza el código para reducir la complejidad ciclomática.")
    
    if not recommendations:
        recommendations.append("• El código parece estar en buen estado. ¡Buen trabajo!")
    
    report_parts.append("\n".join(recommendations))
    
    return "\n".join(report_parts)


def calculate_cyclomatic_complexity(metrics: Dict[str, Any]) -> int:
    """
    Calculate cyclomatic complexity based on metrics.
    
    Time Complexity: O(1) - constant time lookup operations
    
    Args:
        metrics: Metrics dictionary
        
    Returns:
        Complexity score (int)
    """
    language = metrics.get('language', '').lower()
    
    if language == 'python':
        return metrics.get('max_complexity', 0)
    elif language in ['c', 'cpp', 'c++']:
        return metrics.get('estimated_cyclomatic', 0)
    else:
        return 0


def run_code_analysis(
    code: str,
    language: str,
    format_config: Optional[Dict[str, Any]] = None,
    run_metrics: bool = True
) -> Dict[str, Any]:
    """
    Run comprehensive code analysis including format and metrics.
    
    Time Complexity: O(n) where n is the size of the code
    - Format analysis: O(n)
    - Metrics analysis: O(n)
    - Consolidated report: O(n)
    
    Args:
        code: Source code
        language: Programming language
        format_config: Configuration for format analysis
        run_metrics: Whether to run metrics analysis
        
    Returns:
        Dict with consolidated results
    """
    results = {
        "format_results": None,
        "metrics_results": None,
        "consolidated_report": "",
        "success": False
    }
    
    # Run format analysis if config provided - O(n)
    if format_config:
        # This calls an external function, assumed to be O(n)
        format_results = run_format_analysis_configurable(code, language, format_config)
        results["format_results"] = format_results
    
    # Run metrics analysis if enabled - O(n)
    if run_metrics:
        metrics_results = run_metrics_analysis(code, language)
        results["metrics_results"] = metrics_results
    
    # Generate consolidated report - O(n)
    consolidated_report = generate_consolidated_report(
        results.get("format_results"),
        results.get("metrics_results")
    )
    results["consolidated_report"] = consolidated_report
    
    # Determine overall success - O(1)
    format_success = results.get("format_results", {}).get("success", True)
    metrics_success = results.get("metrics_results", {}).get("success", True)
    results["success"] = format_success and metrics_success
    
    return results


def run_complete_analysis(
    code: str,
    language: str,
    format_config: Optional[Dict[str, Any]] = None,
    run_metrics: bool = True
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """
    Run complete analysis and return format results, metrics results, and consolidated report.
    
    Time Complexity: O(n) where n is the size of the code
    - All underlying functions have linear time complexity
    
    Args:
        code: Source code
        language: Programming language
        format_config: Configuration for format analysis
        run_metrics: Whether to run metrics analysis
        
    Returns:
        Tuple: (format_results, metrics_results, consolidated_report)
    """
    try:
        # Run code analysis - O(n)
        analysis_results = run_code_analysis(code, language, format_config, run_metrics)
        return (
            analysis_results.get("format_results"),
            analysis_results.get("metrics_results"),
            analysis_results.get("consolidated_report")
        )
    except Exception as e:
        error_msg = f"Error durante el análisis de código: {e}"
        return None, None, error_msg


"""
------------------------------------------------------------
ALGORITHM COMPLEXITY ANALYSIS SUMMARY
------------------------------------------------------------

The metrics calculator predominantly uses algorithms with linear time complexity:

1. Generic Metrics (O(n) where n is code size):
   - Line counting: O(n)
   - Non-empty line filtering: O(n)
   - Line length calculations: O(n)

2. Python Metrics (O(n)):
   - AST parsing: O(n) - parsing the source code into an AST
   - AST traversal: O(n) - visiting each node exactly once
   - Function analysis: O(f) where f is the number of functions, f < n

3. C/C++ Metrics (O(n)):
   - Line-by-line parsing: O(n)
   - Regex pattern matching: Technically O(n²) in worst case, but practical
     performance is closer to O(n) with modern regex engines and simple patterns

4. Report Generation (O(n)):
   - Format results processing: O(1)
   - Metrics formatting: O(f) where f is the number of functions
   - Rendering final report: O(n)

Space Complexity:
- AST representation: O(n)
- Metrics storage: O(f) where f is the number of functions
- Report generation: O(n)

Optimization Opportunities:
1. For very large files, we could implement incremental parsing
2. For C/C++ parsing, use a proper parser instead of regex for more accurate metrics
3. Implement caching for frequently analyzed files

All algorithms scale linearly with code size, making this solution efficient
for typical code analysis scenarios.
"""

try:
    import copydetect
except ImportError:
    copydetect = None
    log.warning("copydetect no está instalado. El análisis de similitud no funcionará.")

def obtener_sufijo_archivo(lenguaje: str) -> str:
    return {
        "python": ".py", "c": ".c", "java": ".java", "pseint": ".psc"
    }.get(lenguaje.lower(), ".tmp")

def run_similarity_analysis(
    submissions: List[Tuple[int, str, str]],
    min_similarity_threshold: float = 25.0,
    noise_t: int = 25,
    guarantee_t: int = 25
) -> List[Dict[str, Any]]:
    """
    Ejecuta un análisis de similitud sintáctico en un conjunto de entregas,
    comparando cada entrega con todas las demás y evitando duplicados y
    autocomparaciones.
    """
    if not copydetect:
        log.error("copydetect no está disponible. Saltando análisis sintáctico.")
        return []

    if len(submissions) < 2:
        log.warning("Se necesitan al menos 2 entregas para realizar el análisis.")
        return []

    log.info(f"Iniciando análisis sintáctico para {len(submissions)} entregas. Umbral: {min_similarity_threshold}%")
    results = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        file_extensions = set()
        for entrega_id, lang, code in submissions:
            if code and code.strip():
                suffix = obtener_sufijo_archivo(lang)
                file_extensions.add(suffix.lstrip('.'))
                with open(os.path.join(temp_dir, f"{entrega_id}{suffix}"), "w", encoding="utf-8") as f:
                    f.write(code)
        
        try:
            # --- CORRECCIÓN CLAVE ---
            # Se elimina el parámetro 'display_t'. Dejamos que la librería nos
            # devuelva TODOS los resultados y nosotros hacemos el filtrado en Python.
            detector = copydetect.CopyDetector(
                test_dirs=[temp_dir], 
                ref_dirs=[temp_dir], 
                extensions=list(file_extensions),
                noise_t=noise_t, 
                guarantee_t=guarantee_t,
                silent=True
            )
            detector.run()
            
            # get_copied_code_list() ahora devolverá más resultados, que filtraremos a continuación.
            for sim_test, sim_ref, test_path, ref_path, *_ in detector.get_copied_code_list():
                id1 = int(os.path.splitext(os.path.basename(test_path))[0])
                id2 = int(os.path.splitext(os.path.basename(ref_path))[0])

                # La lógica anti-duplicados y anti-autocomparación sigue siendo crucial.
                if id1 < id2:
                    sim_percent = round(max(sim_test, sim_ref) * 100, 2)
                    
                    # Nuestro propio filtrado, más fiable.
                    if sim_percent >= min_similarity_threshold:
                        results.append({
                            "entrega_id_1": id1,
                            "entrega_id_2": id2,
                            "similitud": sim_percent
                        })
        except Exception as e:
            log.error("Fallo en copydetect: %s", e, exc_info=True)

    log.info("Análisis sintáctico completado. Se encontraron %d pares únicos sobre el umbral.", len(results))
    return sorted(results, key=lambda x: x["similitud"], reverse=True)

# Importar librerías necesarias para el análisis semántico


try:
    import torch
    import torch.nn.functional as F
    from transformers import RobertaTokenizer, RobertaModel
    from scipy.spatial.distance import cdist
except ImportError:
    torch = None
    log.warning("PyTorch/Transformers no están instalados. El análisis semántico no funcionará.")

# Se inicializan como None para la carga perezosa (Lazy Loading)
tokenizer_graphcodebert = None
model_graphcodebert = None

"""
def run_semantic_similarity(code1: str, code2: str, similarity_threshold: float = 85.0) -> Optional[float]:
    global tokenizer_graphcodebert, model_graphcodebert

    if not torch or not cosine:
        log.error("Librerías de ML no disponibles (torch, scipy).")
        return None

    if model_graphcodebert is None:
        try:
            log.info("Cargando modelo y tokenizador de GraphCodeBERT por primera vez...")
            tokenizer_graphcodebert = RobertaTokenizer.from_pretrained("YoussefHassan/graphcodebert-plagiarism-detector")
            model_graphcodebert = RobertaModel.from_pretrained("YoussefHassan/graphcodebert-plagiarism-detector")
            log.info("Modelo GraphCodeBERT cargado exitosamente.")
        except Exception as e:
            log.error(f"Fallo crítico al cargar el modelo GraphCodeBERT: {e}")
            return None
    
    try:
        inputs1 = tokenizer_graphcodebert(code1, return_tensors="pt", max_length=512, truncation=True)
        inputs2 = tokenizer_graphcodebert(code2, return_tensors="pt", max_length=512, truncation=True)
        
        with torch.no_grad():
            embedding1 = model_graphcodebert(**inputs1).pooler_output.squeeze()
            embedding2 = model_graphcodebert(**inputs2).pooler_output.squeeze()
        
        similitud_coseno = 1 - cosine(embedding1, embedding2)
        similitud_percent = round(similitud_coseno * 100, 2)

        if similitud_percent >= similarity_threshold:
            log.info(f"Similitud semántica calculada: {similitud_percent}% (supera el umbral)")
        else:
            log.info(f"Similitud semántica calculada: {similitud_percent}% (por debajo del umbral)")

        return similitud_percent
        
    except Exception as e:
        log.error(f"Error durante el análisis semántico con GraphCodeBERT: {e}", exc_info=True)
        return None
"""

def run_semantic_similarity(
    submissions: List[Tuple[int, str, str]],
    min_similarity_threshold: float = 50.0
) -> List[Dict[str, Any]]:
    """
    Calcula la similitud semántica para una lista de entregas usando un modelo
    GraphCodeBERT afinado, comparando todos los pares y devolviendo un ranking.
    """
    global tokenizer_graphcodebert, model_graphcodebert

    if not torch:
        log.error("Librería PyTorch no disponible. Saltando análisis.")
        return []

    if len(submissions) < 2:
        log.warning("Se necesitan al menos 2 entregas para el análisis semántico.")
        return []

    # ---- INICIO: BLOQUE DE CARGA PEREZOSA (LAZY LOADING) ----
    if model_graphcodebert is None:
        try:
            log.info("Cargando modelo de detección de plagio por primera vez (puede tardar)...")
            model_name = "YoussefHassan/graphcodebert-plagiarism-detector"
            tokenizer_graphcodebert = RobertaTokenizer.from_pretrained(model_name)
            model_graphcodebert = RobertaModel.from_pretrained(model_name)
            model_graphcodebert.eval() # Poner en modo evaluación
            log.info(f"Modelo '{model_name}' cargado exitosamente.")
        except Exception as e:
            log.error(f"Fallo crítico al cargar el modelo GraphCodeBERT: {e}")
            return []
    # ---- FIN: BLOQUE DE CARGA PEREZOSA ----

    log.info(f"Iniciando análisis semántico para {len(submissions)} entregas.")
    results = []
    
    try:
        # 1. Extraer los IDs y el código de las entregas
        entrega_ids = [sub[0] for sub in submissions]
        codes_to_encode = [sub[2] for sub in submissions]
        
        # 2. Generar todos los embeddings en un solo lote para máxima eficiencia
        log.info("Generando embeddings para todas las entregas...")
        
        # Tokenizar en lote
        inputs = tokenizer_graphcodebert(
            codes_to_encode, 
            padding=True, 
            truncation=True, 
            max_length=512, 
            return_tensors="pt"
        )

        # Inferencia en lote
        with torch.no_grad():
            # Usamos el pooler_output como lo hace el modelo original que elegiste
            embeddings = model_graphcodebert(**inputs).pooler_output
        
        # 3. Comparar cada par de embeddings de forma eficiente
        log.info("Comparando pares de embeddings...")
        
        # Convertir a numpy para usar cdist (más rápido que un bucle de bucles)
        embeddings_np = embeddings.numpy()
        
        # cdist calcula la distancia del coseno (1 - similitud) para todos los pares
        cosine_dist_matrix = cdist(embeddings_np, embeddings_np, 'cosine')
        
        # La similitud es 1 - distancia
        similarity_matrix = 1 - cosine_dist_matrix

        for i in range(len(embeddings_np)):
            for j in range(i + 1, len(embeddings_np)):
                similitud_percent = round(similarity_matrix[i, j] * 100, 2)
                
                if similitud_percent >= min_similarity_threshold:
                    results.append({
                        "entrega_id_1": entrega_ids[i],
                        "entrega_id_2": entrega_ids[j],
                        "similitud": similitud_percent
                    })
        
    except Exception as e:
        log.error(f"Error durante el análisis semántico: {e}", exc_info=True)

    log.info("Análisis semántico completado. Se encontraron %d pares sobre el umbral.", len(results))
    return sorted(results, key=lambda x: x["similitud"], reverse=True)

