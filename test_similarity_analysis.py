import torch
from analysis_tools import run_similarity_analysis, run_semantic_similarity, copydetect

if __name__ == "__main__":
    print("--- Ejecutando Script de Prueba Exhaustivo para analysis_tools.py ---\n")

    # ======================================================================
    # === 1. PRUEBAS CON LENGUAJE PYTHON ===
    # ======================================================================
    print("="*60)
    print(">>> INICIANDO PRUEBAS CON LENGUAJE PYTHON <<<")
    print("="*60)

    # Código A: Suma de una lista usando un bucle for.
    codigo_py_1 = """
def calcular_suma_total(numeros):
    # Esta función itera sobre una lista para sumar sus elementos.
    acumulador = 0
    for numero in numeros:
        acumulador += numero
    return acumulador
"""
    # Código B: Semánticamente idéntico, pero usando la función `sum()` de Python.
    codigo_py_2_similar = """
def totalizar_lista(valores):
    # Devuelve el total de una lista de números.
    return sum(valores)
"""
    # Código C: Semánticamente diferente (invierte una cadena).
    codigo_py_3_diferente = """
def invertir_cadena(texto):
    # Invierte el orden de los caracteres en un string.
    return texto[::-1]
"""
    entregas_python = [
        (1, "python", codigo_py_1),
        (2, "python", codigo_py_2_similar),
        (3, "python", codigo_py_3_diferente)
    ]

    print("\n--- 1.1 Análisis Sintáctico (copydetect) para Python ---")
    if copydetect:
        pares_sintacticos_py = run_similarity_analysis(entregas_python, entregas_python, noise_thresh=10, guarantee_thresh=10)
        if pares_sintacticos_py:
            for p in pares_sintacticos_py: print(f"  - Entrega {p['entrega_id_1']} vs {p['entrega_id_2']}: {p['similitud']}%")
        else: print("  copydetect no encontró similitudes sintácticas significativas.")
    else: print("  ERROR: copydetect no está disponible.")

    print("\n--- 1.2 Análisis Semántico (GraphCodeBERT) para Python ---")
    if torch:
        print("  Comparando Suma con Bucle (1) vs. Suma con sum() (2):")
        sim_py_1_2 = run_semantic_similarity(codigo_py_1, codigo_py_2_similar)
        print(f"    -> Similitud Esperada: ALTA. Resultado: {sim_py_1_2 or 'Error'}%")
            
        print("\n  Comparando Suma con Bucle (1) vs. Invertir Cadena (3):")
        sim_py_1_3 = run_semantic_similarity(codigo_py_1, codigo_py_3_diferente)
        print(f"    -> Similitud Esperada: BAJA. Resultado: {sim_py_1_3 or 'Error'}%")
    else: print("  ERROR: GraphCodeBERT no está disponible.")

    # ======================================================================
    # === 2. PRUEBAS CON LENGUAJE C ===
    # ======================================================================
    print("\n\n" + "="*60)
    print(">>> INICIANDO PRUEBAS CON LENGUAJE C <<<")
    print("="*60)

    # Código A: Invertir una cadena usando un bucle 'while' y dos punteros.
    codigo_c_1 = """
#include <string.h>
void reverseStringIterative(char* str) {
    int start = 0;
    int end = strlen(str) - 1;
    char temp;
    while (start < end) {
        temp = str[start];
        str[start] = str[end];
        str[end] = temp;
        start++;
        end--;
    }
}
"""
    # Código B: Semánticamente idéntico, pero usando recursividad.
    codigo_c_2_similar = """
#include <string.h>
void swapChars(char* a, char* b) {
    char temp = *a; *a = *b; *b = temp;
}
void reverseStringRecursive(char* str, int start, int end) {
    if (start >= end) return;
    swapChars(str + start, str + end);
    reverseStringRecursive(str, start + 1, end - 1);
}
"""
    # Código C: Semánticamente diferente (encontrar el máximo en un array).
    codigo_c_3_diferente = """
#include <stdio.h>
int findMaxInArray(int arr[], int size) {
    if (size <= 0) return -1;
    int max_val = arr[0];
    for (int i = 1; i < size; i++) {
        if (arr[i] > max_val) max_val = arr[i];
    }
    return max_val;
}
"""
    entregas_c = [
        (4, "c", codigo_c_1), (5, "c", codigo_c_2_similar), (6, "c", codigo_c_3_diferente)
    ]

    print("\n--- 2.1 Análisis Sintáctico (copydetect) para C ---")
    if copydetect:
        pares_sintacticos_c = run_similarity_analysis(entregas_c, entregas_c, noise_thresh=15, guarantee_thresh=15)
        if pares_sintacticos_c:
            for p in pares_sintacticos_c: print(f"  - Entrega {p['entrega_id_1']} vs {p['entrega_id_2']}: {p['similitud']}%")
        else: print("  copydetect no encontró similitudes sintácticas significativas.")
    else: print("  ERROR: copydetect no está disponible.")

    print("\n--- 2.2 Análisis Semántico (GraphCodeBERT) para C ---")
    if torch:
        print("  Comparando Invertir Iterativo (4) vs. Invertir Recursivo (5):")
        sim_c_1_2 = run_semantic_similarity(codigo_c_1, codigo_c_2_similar)
        print(f"    -> Similitud Esperada: ALTA. Resultado: {sim_c_1_2 or 'Error'}%")
            
        print("\n  Comparando Invertir Iterativo (4) vs. Encontrar Máximo (6):")
        sim_c_1_3 = run_semantic_similarity(codigo_c_1, codigo_c_3_diferente)
        print(f"    -> Similitud Esperada: BAJA. Resultado: {sim_c_1_3 or 'Error'}%")
    else: print("  ERROR: GraphCodeBERT no está disponible.")

    # ======================================================================
    # === 3. PRUEBAS CON LENGUAJE JAVA ===
    # ======================================================================
    print("\n\n" + "="*60)
    print(">>> INICIANDO PRUEBAS CON LENGUAJE JAVA <<<")
    print("="*60)

    # Código A: Verificar si un número es primo con un bucle for.
    codigo_java_1 = """
import java.util.ArrayList;
class PrimeChecker {
    public static boolean isPrime(int number) {
        if (number <= 1) {
            return false;
        }
        for (int i = 2; i <= Math.sqrt(number); i++) {
            if (number % i == 0) {
                return false;
            }
        }
        return true;
    }
}
"""
    # Código B: Semánticamente idéntico, pero con optimizaciones y estilo diferente.
    codigo_java_2_similar = """
class NumberUtils {
    public boolean checkPrime(int n) {
        if (n < 2) return false;
        if (n == 2 || n == 3) return true;
        if (n % 2 == 0 || n % 3 == 0) return false;
        long i = 5;
        while (i * i <= n) {
            if (n % i == 0 || n % (i + 2) == 0) return false;
            i += 6;
        }
        return true;
    }
}
"""
    # Código C: Semánticamente diferente (factorial de un número).
    codigo_java_3_diferente = """
class MathTools {
    public static long factorial(int num) {
        if (num < 0) return -1; // Error
        long result = 1;
        for (int i = 1; i <= num; i++) {
            result *= i;
        }
        return result;
    }
}
"""
    entregas_java = [
        (7, "java", codigo_java_1), (8, "java", codigo_java_2_similar), (9, "java", codigo_java_3_diferente)
    ]

    print("\n--- 3.1 Análisis Sintáctico (copydetect) para Java ---")
    if copydetect:
        pares_sintacticos_java = run_similarity_analysis(entregas_java, entregas_java, noise_thresh=15, guarantee_thresh=15)
        if pares_sintacticos_java:
            for p in pares_sintacticos_java: print(f"  - Entrega {p['entrega_id_1']} vs {p['entrega_id_2']}: {p['similitud']}%")
        else: print("  copydetect no encontró similitudes sintácticas significativas.")
    else: print("  ERROR: copydetect no está disponible.")

    print("\n--- 3.2 Análisis Semántico (GraphCodeBERT) para Java ---")
    if torch:
        print("  Comparando Es Primo (7) vs. Es Primo Optimizado (8):")
        sim_java_1_2 = run_semantic_similarity(codigo_java_1, codigo_java_2_similar)
        print(f"    -> Similitud Esperada: ALTA. Resultado: {sim_java_1_2 or 'Error'}%")
            
        print("\n  Comparando Es Primo (7) vs. Factorial (9):")
        sim_java_1_3 = run_semantic_similarity(codigo_java_1, codigo_java_3_diferente)
        print(f"    -> Similitud Esperada: BAJA. Resultado: {sim_java_1_3 or 'Error'}%")
    else: print("  ERROR: GraphCodeBERT no está disponible.")


    print("\n\n--- Fin del script de prueba ---")