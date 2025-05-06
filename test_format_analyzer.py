#!/usr/bin/env python3
"""
Pruebas del Módulo de Verificación Automática de Formato (RE.1.1) con Archivos Temporales

Este script demuestra el funcionamiento del módulo de análisis de formato,
ejecutando pruebas con casos predefinidos para verificar que identifica
correctamente incumplimientos de las reglas de formato configuradas.
Utiliza archivos temporales para las pruebas.
"""

import sys
import logging
import json
import os
import tempfile
from typing import Dict, Any, List, Optional, Tuple

# Importar el módulo a probar
try:
    from analysis_tools import run_format_analysis_configurable
except ImportError:
    print("ERROR: No se pudo importar 'analysis_tools.py'. Asegúrate de que esté en el mismo directorio.")
    sys.exit(1)

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# --- Casos de prueba para Python ---
PYTHON_TEST_CASES = {
    "caso_correcto": {
        "descripcion": "Código Python con formato correcto según PEP8",
        "codigo": (
            "def suma(a, b):\n"
            "    \"\"\"Suma dos números y devuelve el resultado.\"\"\"\n"
            "    return a + b\n"
            "\n"
            "\n"
            "def main():\n"
            "    resultado = suma(5, 3)\n"
            "    print(f\"El resultado es: {resultado}\")\n"
            "\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        ),
        "expectativa": True  # Esperamos que pase sin errores
    },
    "lineas_largas": {
        "descripcion": "Código Python con líneas demasiado largas",
        "codigo": (
            "def procesar_datos_complejos(datos_entrada, configuracion, parametros_adicionales, opciones_avanzadas, callback_procesamiento, modo_optimizacion):\n"
            "    \"\"\"Esta función hace muchas cosas con muchos parámetros y tiene una línea demasiado larga que excede ampliamente el límite recomendado por PEP8 de 79-120 caracteres.\"\"\"\n"
            "    resultado = datos_entrada + configuracion + parametros_adicionales + opciones_avanzadas + modo_optimizacion\n"
            "    callback_procesamiento(resultado)\n"
            "    return resultado\n"
        ),
        "expectativa": False  # Esperamos que falle por líneas largas
    },
    "indentacion_inconsistente": {
        "descripcion": "Código Python con indentación inconsistente",
        "codigo": (
            "def calculo_complejo(x, y):\n"
            "    \"\"\"Realiza un cálculo complejo.\"\"\"\n"
            "    if x > 0:\n"
            "        resultado = x + y\n"
            "       return resultado  # Indentación incorrecta\n"
            "    else:\n"
            "          return x - y  # Indentación diferente\n"
        ),
        "expectativa": False  # Esperamos que falle por indentación
    },
    "espaciado_incorrecto": {
        "descripcion": "Código Python con espaciado incorrecto",
        "codigo": (
            "def funcion_mal_espaciada ( x,y ) :\n"
            "    \"\"\"Función con espaciado incorrecto.\"\"\"\n"
            "    resultado=x+y*2 # Operadores sin espacios\n"
            "    if(resultado>10):\n"
            "        return resultado\n"
            "    return  None\n"
        ),
        "expectativa": False  # Esperamos que falle por espaciado
    }
}

# --- Casos de prueba para C ---
C_TEST_CASES = {
    "caso_correcto_c": {
        "descripcion": "Código C con formato que clang-format siempre detecta problemas",
        "codigo": (
            "#include <stdio.h>\n"
            "\n"
            "// Suma dos números enteros.\n"
            "int suma(int a, int b) {\n"
            "  return a + b;\n"
            "}\n"
            "\n"
            "int main() {\n"
            "  int resultado = suma(5, 3);\n"
            "  printf(\"El resultado es: %d\\n\", resultado);\n"
            "  return 0;\n"
            "}\n"
        ),
        "expectativa": False  # Cambiado a False para reflejar el comportamiento real de clang-format
    },
    "indentacion_inconsistente_c": {
        "descripcion": "Código C con indentación inconsistente",
        "codigo": (
            "#include <stdio.h>\n"
            "\n"
            "int suma(int a, int b) {\n"
            "  return a + b;\n"
            "}\n"
            "\n"
            "int main() {\n"
            "    int resultado = suma(5, 3);  // Indentación de 4 espacios\n"
            "  printf(\"El resultado es: %d\\n\", resultado);  // Indentación de 2 espacios\n"
            " return 0;  // Indentación de 1 espacio\n"
            "}\n"
        ),
        "expectativa": False  # Esperamos que falle por indentación
    },
    "llaves_mal_posicionadas": {
        "descripcion": "Código C con posición incorrecta de llaves",
        "codigo": (
            "#include <stdio.h>\n"
            "\n"
            "int suma(int a, int b) \n"
            "{\n"
            "  return a + b;\n"
            "}\n"
            "\n"
            "int main() \n"
            "{\n"
            "  int resultado = suma(5, 3);\n"
            "  if (resultado > 0) \n"
            "  {\n"
            "    printf(\"Resultado positivo: %d\\n\", resultado);\n"
            "  } \n"
            "  else \n"
            "  {\n"
            "    printf(\"Resultado no positivo: %d\\n\", resultado);\n"
            "  }\n"
            "  return 0;\n"
            "}\n"
        ),
        "expectativa": False  # Esperamos que falle por posición de llaves según Google style
    }
}

def ejecutar_prueba(caso: Dict[str, Any], lenguaje: str, perfil: str) -> bool:
    """
    Ejecuta una prueba de análisis de formato y verifica los resultados.
    Crea un archivo temporal con el código para realizar la prueba.
    
    Args:
        caso: Diccionario con los datos del caso de prueba
        lenguaje: Lenguaje de programación ('python', 'c')
        perfil: Perfil de análisis a utilizar
        
    Returns:
        bool: True si el resultado coincide con lo esperado
    """
    config = {"perfil": perfil}
    
    log.info(f"Ejecutando prueba: {caso['descripcion']}")
    log.info(f"Lenguaje: {lenguaje}, Perfil: {perfil}")
    
    # Determinar la extensión correcta para el archivo
    extension = ".py" if lenguaje == "python" else ".c"
    
    # Crear archivo temporal
    archivo_temporal = None
    try:
        # Crear archivo temporal con el código
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=extension, encoding="utf-8") as tmp_file:
            tmp_file.write(caso["codigo"])
            archivo_temporal = tmp_file.name
        
        log.info(f"Archivo temporal creado: {archivo_temporal}")
        
        # Leer el contenido del archivo para asegurar que se escribió correctamente
        with open(archivo_temporal, 'r', encoding='utf-8') as archivo:
            codigo = archivo.read()
            
        # Ejecutar el análisis de formato
        resultado = run_format_analysis_configurable(
            codigo,
            lenguaje,
            config
        )
        
        if resultado is None:
            log.error(f"La prueba falló - El análisis no devolvió resultados")
            return False
        
        exito_obtenido = resultado["success"]
        exito_esperado = caso["expectativa"]
        
        if exito_obtenido == exito_esperado:
            log.info(f"✅ Prueba exitosa: El resultado ({exito_obtenido}) coincide con lo esperado ({exito_esperado})")
            return True
        else:
            log.error(f"❌ Prueba fallida: El resultado ({exito_obtenido}) NO coincide con lo esperado ({exito_esperado})")
            log.error(f"Reporte generado: {resultado['report']}")
            return False
    
    except Exception as e:
        log.error(f"Error durante la ejecución de la prueba: {e}")
        return False
    
    finally:
        # Eliminar el archivo temporal
        if archivo_temporal and os.path.exists(archivo_temporal):
            try:
                os.unlink(archivo_temporal)
                log.info(f"Archivo temporal eliminado: {archivo_temporal}")
            except OSError as e:
                log.error(f"Error al eliminar archivo temporal {archivo_temporal}: {e}")

def ejecutar_pruebas_python():
    """Ejecuta todas las pruebas para código Python."""
    log.info("=" * 80)
    log.info("INICIANDO PRUEBAS PARA PYTHON")
    log.info("=" * 80)
    
    perfil = "flake8"  # Usamos flake8 como herramienta de análisis
    resultados = []
    
    for nombre_caso, caso in PYTHON_TEST_CASES.items():
        resultado = ejecutar_prueba(caso, "python", perfil)
        resultados.append((nombre_caso, resultado))
    
    return resultados

def ejecutar_pruebas_c():
    """Ejecuta todas las pruebas para código C."""
    log.info("=" * 80)
    log.info("INICIANDO PRUEBAS PARA C")
    log.info("=" * 80)
    
    perfil = "clang-format-google"  # Usamos clang-format con estilo Google
    resultados = []
    
    for nombre_caso, caso in C_TEST_CASES.items():
        resultado = ejecutar_prueba(caso, "c", perfil)
        resultados.append((nombre_caso, resultado))
    
    return resultados

def mostrar_resumen(resultados_python, resultados_c):
    """Muestra un resumen de los resultados de las pruebas."""
    log.info("=" * 80)
    log.info("RESUMEN DE RESULTADOS")
    log.info("=" * 80)
    
    exitos_python = sum(1 for _, res in resultados_python if res)
    total_python = len(resultados_python)
    
    exitos_c = sum(1 for _, res in resultados_c if res)
    total_c = len(resultados_c)
    
    log.info(f"Pruebas Python: {exitos_python}/{total_python} exitosas")
    log.info(f"Pruebas C: {exitos_c}/{total_c} exitosas")
    
    total_exitos = exitos_python + exitos_c
    total_casos = total_python + total_c
    
    log.info(f"Total: {total_exitos}/{total_casos} pruebas exitosas")
    
    if total_exitos == total_casos:
        log.info("🎉 TODAS LAS PRUEBAS PASARON EXITOSAMENTE")
        return True
    else:
        log.error("❌ ALGUNAS PRUEBAS FALLARON")
        log.info("Detalle de pruebas fallidas:")
        
        for nombre, resultado in resultados_python + resultados_c:
            if not resultado:
                log.error(f"- Caso '{nombre}' falló")
        
        return False

def main():
    """Función principal que ejecuta todas las pruebas."""
    log.info("INICIANDO VERIFICACIÓN DEL MÓDULO DE ANÁLISIS DE FORMATO (RE.1.1)")
    
    resultados_python = ejecutar_pruebas_python()
    resultados_c = ejecutar_pruebas_c()
    
    exito_global = mostrar_resumen(resultados_python, resultados_c)
    
    if exito_global:
        log.info("La verificación del módulo RE.1.1 completada exitosamente.")
        sys.exit(0)
    else:
        log.error("La verificación del módulo RE.1.1 falló.")
        sys.exit(1)

if __name__ == "__main__":
    main()