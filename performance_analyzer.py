"""
Módulo para análisis de rendimiento algorítmico (performance_analyzer.py)

Este módulo implementa análisis de rendimiento para código en Python y C,
evaluando la complejidad temporal (Big O) y uso de recursos.
"""

import subprocess
import tempfile
import os
import sys
import re
import json
import math
import statistics
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union

# Intentar importar herramientas específicas para análisis
try:
    import radon.complexity as radon_cc
    import radon.raw as radon_raw
    import radon.metrics as radon_metrics
    RADON_AVAILABLE = True
except ImportError:
    RADON_AVAILABLE = False
    logging.warning("Radon no está disponible. Instale con: pip install radon")

# Configuración de logging
log = logging.getLogger(__name__)
if not log.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)

# Constante para nombre de herramienta en BD
TOOL_PERFORMANCE_ANALYZER = "performance-analyzer"

# Configuración de análisis
DEFAULT_TEST_SIZES = [10, 100, 1000, 10000]  # Tamaños de entrada para pruebas
MAX_EXECUTION_TIME = 300  # Tiempo máximo de ejecución (segundos)
MIN_TEST_SAMPLES = 3  # Mínimo de muestras para estimación válida

# Mapeo de complejidades algorítmicas y sus descripciones
COMPLEXITY_DESCRIPTIONS = {
    "O(1)": "Constante - Tiempo independiente del tamaño de entrada",
    "O(log n)": "Logarítmica - Crecimiento muy lento",
    "O(n)": "Lineal - Tiempo proporcional al tamaño de entrada",
    "O(n log n)": "Linearítmica - Típica de algoritmos eficientes de ordenación",
    "O(n²)": "Cuadrática - Degradación significativa con datos grandes",
    "O(n³)": "Cúbica - Alta complejidad, solo para datos pequeños",
    "O(2^n)": "Exponencial - Prohibitiva para conjuntos de datos medianos o grandes"
}


class PerformanceResult:
    """Almacena resultados de una prueba de rendimiento para un tamaño específico"""
    
    def __init__(self, size: int, time_ms: float, memory_kb: Optional[float]=None, 
                 error: Optional[str]=None, timeout: bool=False):
        self.size = size
        self.time_ms = time_ms
        self.memory_kb = memory_kb
        self.error = error
        self.timeout = timeout
    
    def __str__(self) -> str:
        """Representación en texto del resultado"""
        memory_str = f", Memoria: {self.memory_kb/1024:.2f} MB" if self.memory_kb else ""
        if self.error:
            return f"Tamaño {self.size}: ERROR - {self.error}"
        elif self.timeout:
            return f"Tamaño {self.size}: TIMEOUT (> {self.time_ms/1000:.1f}s)"
        else:
            return f"Tamaño {self.size}: {self.time_ms:.2f} ms{memory_str}"


def analyze_python_with_radon(code: str) -> Dict[str, Any]:
    """
    Analiza código Python utilizando Radon para obtener métricas estáticas.
    
    Args:
        code: Código fuente Python
        
    Returns:
        Dict con métricas de complejidad y mantenibilidad
    """
    if not RADON_AVAILABLE:
        return {"error": "Radon no está disponible. Instale con: pip install radon"}
    
    try:
        # Análisis de complejidad ciclomática
        cc_results = list(radon_cc.cc_visit(code))
        
        # Análisis raw (métricas básicas)
        raw_metrics = radon_raw.analyze(code)
        
        # Análisis de mantenibilidad
        mi_result = radon_metrics.mi_visit(code, True)
        
        # Preparar resultados
        results = {
            "complexity": {
                "average": sum(result.complexity for result in cc_results) / len(cc_results) if cc_results else 0,
                "max": max(result.complexity for result in cc_results) if cc_results else 0,
                "functions": [
                    {
                        "name": result.name,
                        "complexity": result.complexity,
                        "rank": result.rank
                    }
                    for result in cc_results
                ]
            },
            "maintainability": mi_result,
            "raw_metrics": {
                "loc": raw_metrics.loc,
                "lloc": raw_metrics.lloc,
                "comments": raw_metrics.comments,
                "multi_comments": raw_metrics.multi,
                "blank_lines": raw_metrics.blank
            }
        }
        
        return results
        
    except Exception as e:
        log.error(f"Error analizando código con Radon: {e}", exc_info=True)
        return {"error": f"Error en análisis Radon: {e}"}


def analyze_c_complexity(code: str) -> Dict[str, Any]:
    """
    Analiza código C para estimar complejidad.
    
    Args:
        code: Código fuente C
        
    Returns:
        Dict con métricas de complejidad estimadas
    """
    try:
        # Patrones para identificar estructuras de control en C
        patterns = {
            "if_count": re.compile(r'\bif\s*\('),
            "else_count": re.compile(r'\belse\b'),
            "for_count": re.compile(r'\bfor\s*\('),
            "while_count": re.compile(r'\bwhile\s*\('),
            "switch_count": re.compile(r'\bswitch\s*\('),
            "case_count": re.compile(r'\bcase\s+'),
            "goto_count": re.compile(r'\bgoto\s+'),
            "function_count": re.compile(r'(\w+)\s+(\w+)\s*\([^)]*\)\s*{')
        }
        
        # Contar ocurrencias
        counts = {name: len(pattern.findall(code)) for name, pattern in patterns.items()}
        
        # Extraer nombres de funciones
        function_matches = patterns["function_count"].findall(code)
        functions = []
        
        # Analizar complejidad por función
        for ret_type, func_name in function_matches:
            if func_name != "main":  # Excluir función main
                # Extraer el cuerpo de la función con regex
                func_pattern = re.compile(rf'{ret_type}\s+{func_name}\s*\([^)]*\)\s*{{(.*?)}}', re.DOTALL)
                func_matches = func_pattern.findall(code)
                
                if func_matches:
                    func_body = func_matches[0]
                    # Estimar complejidad ciclomática
                    # CC = 1 + número de decisiones (if, for, while, case)
                    complexity = 1
                    complexity += len(re.findall(r'\bif\s*\(', func_body))
                    complexity += len(re.findall(r'\bfor\s*\(', func_body))
                    complexity += len(re.findall(r'\bwhile\s*\(', func_body))
                    complexity += len(re.findall(r'\bcase\s+', func_body))
                    
                    # Determinar rango de complejidad
                    rank = "A"  # Simple: 1-5
                    if complexity > 10:
                        rank = "C"  # Complejo: >10
                    elif complexity > 5:
                        rank = "B"  # Moderado: 6-10
                    
                    functions.append({
                        "name": func_name,
                        "complexity": complexity,
                        "rank": rank
                    })
        
        # Calcular métricas agregadas
        avg_complexity = sum(f["complexity"] for f in functions) / len(functions) if functions else 0
        max_complexity = max(f["complexity"] for f in functions) if functions else 0
        
        # Preparar resultados
        results = {
            "complexity": {
                "average": avg_complexity,
                "max": max_complexity,
                "functions": functions
            },
            "control_structures": counts,
            "estimated_cyclomatic": sum(1 for f in functions if f["complexity"] > 1)
        }
        
        return results
        
    except Exception as e:
        log.error(f"Error analizando código C: {e}", exc_info=True)
        return {"error": f"Error en análisis de código C: {e}"}


def prepare_python_profiling(code: str, size: int) -> Tuple[str, List[str]]:
    """
    Prepara un wrapper de código Python con profiling y generación de datos de prueba.
    
    Args:
        code: Código fuente original
        size: Tamaño de entrada para la prueba
        
    Returns:
        Tuple con (ruta_archivo_temporal, comando_para_ejecutar)
    """
    # Identificar función principal
    main_function = extract_main_function(code)
    if not main_function:
        raise ValueError("No se pudo identificar una función principal en el código")
    
    # Crear archivo temporal con profiling
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False, encoding='utf-8') as f:
        profiling_code = f"""
import cProfile
import pstats
import io
import time
import sys
import json
import traceback
import random
import resource

# Código original del estudiante
{code}

# Wrapper para profiling
if __name__ == "__main__":
    try:
        # Generar datos de prueba
        test_size = {size}
        data = list(range(test_size))
        random.shuffle(data)
        
        # Medir uso de recursos iniciales
        start_rusage = resource.getrusage(resource.RUSAGE_SELF)
        
        # Ejecutar con profiling
        profile = cProfile.Profile()
        profile.enable()
        start_time = time.time()
        
        # Llamar a la función principal
        result = {main_function}(data)
        
        # Detener mediciones
        end_time = time.time()
        profile.disable()
        end_rusage = resource.getrusage(resource.RUSAGE_SELF)
        
        # Calcular métricas
        execution_time_ms = (end_time - start_time) * 1000
        memory_kb = end_rusage.ru_maxrss - start_rusage.ru_maxrss
        
        # Formatear resultados de profiling
        s = io.StringIO()
        ps = pstats.Stats(profile, stream=s).sort_stats('cumulative')
        ps.print_stats(10)  # Limitar a 10 funciones más significativas
        profile_text = s.getvalue()
        
        # Resultados en formato JSON
        results = {{
            "time_ms": execution_time_ms,
            "memory_kb": memory_kb,
            "profile": profile_text
        }}
        
        print(json.dumps(results))
        sys.exit(0)
        
    except Exception as e:
        error = {{
            "error": str(e),
            "traceback": traceback.format_exc()
        }}
        print(json.dumps(error), file=sys.stderr)
        sys.exit(1)
"""
        f.write(profiling_code)
        tmp_path = f.name
    
    # Comando para ejecutar
    python_cmd = sys.executable or 'python3'
    return tmp_path, [python_cmd, tmp_path]


def prepare_c_profiling(code: str, size: int) -> Tuple[str, str, List[str]]:
    """
    Prepara un wrapper de código C con medición de tiempo y generación de datos de prueba.
    
    Args:
        code: Código fuente original
        size: Tamaño de entrada para la prueba
        
    Returns:
        Tuple con (ruta_archivo_fuente, ruta_ejecutable, comando_para_ejecutar)
    """
    # Identificar función principal
    main_function = extract_c_main_function(code)
    
    # Crear archivo temporal
    with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False, encoding='utf-8') as f:
        # Verificar si gprof está disponible
        has_gprof = False
        try:
            subprocess.run(['which', 'gprof'], check=True, capture_output=True)
            has_gprof = True
        except (subprocess.SubprocessError, FileNotFoundError):
            log.warning("gprof no está disponible para profiling de C")
        
        # Crear wrapper con instrumentación
        if has_gprof:
            profiling_code = f"""
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
#include <sys/time.h>
#include <sys/resource.h>

// Código original
{code}

// Wrapper para profiling con gprof
int main() {{
    // Generar datos de prueba
    const int SIZE = {size};
    int* data = (int*)malloc(SIZE * sizeof(int));
    if (!data) {{
        fprintf(stderr, "{{\\\"error\\\": \\\"Error de asignación de memoria\\\"}}\\n");
        return 1;
    }}
    
    // Inicializar datos
    srand(time(NULL));
    for (int i = 0; i < SIZE; i++) {{
        data[i] = rand() % 10000;
    }}
    
    // Medir rendimiento
    struct timeval start_time, end_time;
    struct rusage start_usage, end_usage;
    
    getrusage(RUSAGE_SELF, &start_usage);
    gettimeofday(&start_time, NULL);
    
    // Llamar a la función principal
    {f"int result = {main_function}(data, SIZE);" if main_function else "// No se pudo detectar función principal"}
    
    // Finalizar mediciones
    gettimeofday(&end_time, NULL);
    getrusage(RUSAGE_SELF, &end_usage);
    
    // Calcular métricas
    long time_ms = ((end_time.tv_sec - start_time.tv_sec) * 1000) + 
                   ((end_time.tv_usec - start_time.tv_usec) / 1000);
    long memory_kb = end_usage.ru_maxrss - start_usage.ru_maxrss;
    
    // Imprimir resultados como JSON
    printf("{{\\\"time_ms\\\": %ld, \\\"memory_kb\\\": %ld}}\\n", time_ms, memory_kb);
    
    free(data);
    return 0;
}}
"""
        else:
            # Versión simple sin gprof
            profiling_code = f"""
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
#include <sys/time.h>
#include <sys/resource.h>

// Código original
{code}

// Wrapper simple para medición de tiempo
int main() {{
    // Generar datos de prueba
    const int SIZE = {size};
    int* data = (int*)malloc(SIZE * sizeof(int));
    if (!data) {{
        fprintf(stderr, "{{\\\"error\\\": \\\"Error de asignación de memoria\\\"}}\\n");
        return 1;
    }}
    
    // Inicializar datos
    srand(time(NULL));
    for (int i = 0; i < SIZE; i++) {{
        data[i] = rand() % 10000;
    }}
    
    // Medir rendimiento
    struct timeval start_time, end_time;
    struct rusage start_usage, end_usage;
    
    getrusage(RUSAGE_SELF, &start_usage);
    gettimeofday(&start_time, NULL);
    
    // Llamar a la función principal
    {f"int result = {main_function}(data, SIZE);" if main_function else "// No se pudo detectar función principal"}
    
    // Finalizar mediciones
    gettimeofday(&end_time, NULL);
    getrusage(RUSAGE_SELF, &end_usage);
    
    // Calcular métricas
    long time_ms = ((end_time.tv_sec - start_time.tv_sec) * 1000) + 
                   ((end_time.tv_usec - start_time.tv_usec) / 1000);
    long memory_kb = end_usage.ru_maxrss - start_usage.ru_maxrss;
    
    // Imprimir resultados como JSON
    printf("{{\\\"time_ms\\\": %ld, \\\"memory_kb\\\": %ld}}\\n", time_ms, memory_kb);
    
    free(data);
    return 0;
}}
"""
        f.write(profiling_code)
        source_path = f.name
    
    # Compilar con flags adecuados
    executable_path = os.path.splitext(source_path)[0] + ('.exe' if sys.platform == 'win32' else '')
    
    if has_gprof:
        compile_command = ['gcc', '-Wall', '-pg', '-O0', source_path, '-o', executable_path]
    else:
        compile_command = ['gcc', '-Wall', '-O0', source_path, '-o', executable_path]
    
    try:
        process = subprocess.run(compile_command, capture_output=True, text=True, timeout=60)
        if process.returncode != 0:
            raise ValueError(f"Error compilando código C: {process.stderr}")
    except subprocess.TimeoutExpired:
        raise TimeoutError("Timeout durante compilación")
    
    # Comando para ejecutar
    return source_path, executable_path, [executable_path]


def extract_main_function(code: str) -> Optional[str]:
    """
    Extrae el nombre de la función principal en código Python.
    
    Args:
        code: Código fuente Python
        
    Returns:
        Nombre de la función principal o None
    """
    # Intentar usar AST (más preciso)
    try:
        import ast
        
        class FunctionVisitor(ast.NodeVisitor):
            def __init__(self):
                self.functions = []
                
            def visit_FunctionDef(self, node):
                self.functions.append(node.name)
                self.generic_visit(node)
        
        tree = ast.parse(code)
        visitor = FunctionVisitor()
        visitor.visit(tree)
        
        if visitor.functions:
            # Heurística: buscar funciones con nombres típicos de algoritmos
            common_names = ['sort', 'search', 'find', 'solve', 'process', 'calculate', 'merge', 'partition']
            for name in common_names:
                for func in visitor.functions:
                    if name in func.lower():
                        return func
            
            # Si no hay coincidencias, usar la primera función
            return visitor.functions[0]
        
    except (ImportError, SyntaxError) as e:
        log.warning(f"Error analizando código con AST: {e}")
    
    # Fallback: regex
    try:
        func_pattern = re.compile(r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')
        matches = func_pattern.findall(code)
        
        if matches:
            return matches[0]
    
    except Exception as e:
        log.warning(f"Error analizando código con regex: {e}")
    
    return None


def extract_c_main_function(code: str) -> Optional[str]:
    """
    Extrae el nombre de la función principal en código C (que no sea main).
    
    Args:
        code: Código fuente C
        
    Returns:
        Nombre de la función principal o None
    """
    # Buscar definiciones de funciones
    func_pattern = re.compile(r'(\w+)\s+(\w+)\s*\([^)]*\)\s*{')
    matches = func_pattern.findall(code)
    
    # Filtrar función main
    candidates = []
    for ret_type, name in matches:
        if name != 'main':
            candidates.append(name)
    
    if not candidates:
        return None
    
    # Heurística: priorizar funciones con nombres típicos
    algo_keywords = ['sort', 'search', 'find', 'solve', 'process', 'calc', 'merge', 'partition']
    for keyword in algo_keywords:
        for func in candidates:
            if keyword in func.lower():
                return func
    
    # Si no hay coincidencias, usar la primera función
    return candidates[0]


def run_performance_tests(code: str, language: str) -> List[PerformanceResult]:
    """
    Ejecuta pruebas de rendimiento con diferentes tamaños de entrada.
    
    Args:
        code: Código fuente
        language: Lenguaje de programación
        
    Returns:
        Lista de resultados de rendimiento
    """
    results = []
    temp_files = []  # Para limpiar después
    
    try:
        for size in DEFAULT_TEST_SIZES:
            log.info(f"Ejecutando prueba de rendimiento para tamaño {size}")
            
            try:
                # Preparar código con profiling
                if language.lower() == 'python':
                    tmp_path, command = prepare_python_profiling(code, size)
                    temp_files.append(tmp_path)
                elif language.lower() in ['c', 'cpp', 'c++']:
                    source_path, executable_path, command = prepare_c_profiling(code, size)
                    temp_files.extend([source_path, executable_path])
                else:
                    log.warning(f"Lenguaje no soportado para análisis de rendimiento: {language}")
                    break
                
                # Calcular timeout adaptativo
                timeout = min(MAX_EXECUTION_TIME, max(30, size // 100))
                
                # Ejecutar prueba
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                if process.returncode == 0:
                    # Procesar salida JSON
                    try:
                        result_data = json.loads(process.stdout)
                        
                        # Extraer métricas básicas
                        time_ms = result_data.get('time_ms', 0)
                        memory_kb = result_data.get('memory_kb')
                        
                        # Guardar resultados
                        results.append(PerformanceResult(
                            size=size,
                            time_ms=time_ms,
                            memory_kb=memory_kb
                        ))
                        
                    except json.JSONDecodeError as e:
                        results.append(PerformanceResult(
                            size=size,
                            time_ms=0,
                            error=f"Error decodificando JSON: {e}"
                        ))
                
                else:
                    # Error en la ejecución
                    error_msg = "Error desconocido"
                    try:
                        error_data = json.loads(process.stderr)
                        error_msg = error_data.get('error', process.stderr)
                    except:
                        error_msg = process.stderr or "Error desconocido"
                    
                    results.append(PerformanceResult(
                        size=size,
                        time_ms=0,
                        error=error_msg
                    ))
            
            except subprocess.TimeoutExpired:
                # Timeout durante la ejecución
                results.append(PerformanceResult(
                    size=size,
                    time_ms=timeout * 1000,  # Convertir a ms
                    timeout=True
                ))
                
                # No probar tamaños mayores si ya hay timeout
                log.warning(f"Timeout en tamaño {size} - Omitiendo tamaños mayores")
                break
                
            except Exception as e:
                log.error(f"Error en prueba de tamaño {size}: {e}", exc_info=True)
                results.append(PerformanceResult(
                    size=size,
                    time_ms=0,
                    error=str(e)
                ))
    
    finally:
        # Limpiar archivos temporales
        for file_path in temp_files:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception as e:
                log.warning(f"Error eliminando archivo temporal {file_path}: {e}")
    
    return results


def estimate_complexity(results: List[PerformanceResult]) -> Tuple[str, float]:
    """
    Estima la complejidad algorítmica (Big O) basada en los resultados de rendimiento.
    
    Args:
        results: Lista de resultados de pruebas
        
    Returns:
        Tupla con (complejidad_estimada, nivel_confianza)
    """
    # Filtrar resultados válidos (sin errores ni timeouts)
    valid_results = [r for r in results if not r.error and not r.timeout and r.time_ms > 0]
    
    if len(valid_results) < MIN_TEST_SAMPLES:
        return "Indeterminada", 0.0
    
    # Extraer tamaños y tiempos
    sizes = [r.size for r in valid_results]
    times = [r.time_ms for r in valid_results]
    
    # Calcular errores con diferentes modelos de complejidad
    errors = {}
    
    # Normalizar tiempos para comparación
    max_time = max(times)
    normalized_times = [t / max_time for t in times]
    
    # O(1)
    const_expected = [1.0 for _ in sizes]
    const_error = sum((t - e)**2 for t, e in zip(normalized_times, const_expected)) / len(sizes)
    errors["O(1)"] = const_error
    
    # O(log n)
    try:
        log_expected = [math.log2(s) if s > 0 else 0.1 for s in sizes]
        max_log = max(log_expected)
        if max_log > 0:
            normalized_log = [l / max_log for l in log_expected]
            log_error = sum((t - l)**2 for t, l in zip(normalized_times, normalized_log)) / len(sizes)
            errors["O(log n)"] = log_error
    except:
        errors["O(log n)"] = float('inf')
    
    # O(n)
    linear_expected = [s / max(sizes) for s in sizes]
    linear_error = sum((t - l)**2 for t, l in zip(normalized_times, linear_expected)) / len(sizes)
    errors["O(n)"] = linear_error
    
    # O(n log n)
    try:
        nlogn_expected = [(s * math.log2(s if s > 0 else 0.1)) for s in sizes]
        max_nlogn = max(nlogn_expected)
        if max_nlogn > 0:
            normalized_nlogn = [nl / max_nlogn for nl in nlogn_expected]
            nlogn_error = sum((t - nl)**2 for t, nl in zip(normalized_times, normalized_nlogn)) / len(sizes)
            errors["O(n log n)"] = nlogn_error
    except:
        errors["O(n log n)"] = float('inf')
    
    # O(n²)
    quadratic_expected = [(s / max(sizes))**2 for s in sizes]
    quadratic_error = sum((t - q)**2 for t, q in zip(normalized_times, quadratic_expected)) / len(sizes)
    errors["O(n²)"] = quadratic_error
    
    # O(n³)
    cubic_expected = [(s / max(sizes))**3 for s in sizes]
    cubic_error = sum((t - c)**2 for t, c in zip(normalized_times, cubic_expected)) / len(sizes)
    errors["O(n³)"] = cubic_error
    
    # O(2^n)
    try:
        # Usar factor de escala para evitar overflow
        scale_factor = 10.0 / max(sizes)
        exp_expected = [2**(s * scale_factor) for s in sizes]
        max_exp = max(exp_expected)
        if max_exp > 0:
            normalized_exp = [e / max_exp for e in exp_expected]
            exp_error = sum((t - e)**2 for t, e in zip(normalized_times, normalized_exp)) / len(sizes)
            errors["O(2^n)"] = exp_error
    except:
        errors["O(2^n)"] = float('inf')
    
    # Encontrar el modelo con menor error
    best_complexity = min(errors.items(), key=lambda x: x[1])
    complexity_name, error_value = best_complexity
    
    # Calcular nivel de confianza (inversamente proporcional al error)
    confidence = 1.0 / (1.0 + error_value)
    
    return complexity_name, confidence


def generate_performance_report(
    results: List[PerformanceResult],
    static_analysis: Dict[str, Any],
    estimated_complexity: Tuple[str, float]
) -> str:
    """
    Genera un informe detallado del análisis de rendimiento.
    
    Args:
        results: Resultados de pruebas de rendimiento
        static_analysis: Resultados de análisis estático
        estimated_complexity: Complejidad estimada y nivel de confianza
        
    Returns:
        Informe formateado
    """
    complexity, confidence = estimated_complexity
    
    # Formatear nivel de confianza
    confidence_level = "Baja"
    if confidence >= 0.9:
        confidence_level = "Alta"
    elif confidence >= 0.7:
        confidence_level = "Media"
    
    # Preparar informe
    report_lines = []
    report_lines.append("=== ANÁLISIS DE RENDIMIENTO ALGORÍTMICO ===\n")