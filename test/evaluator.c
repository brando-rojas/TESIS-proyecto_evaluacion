#include <stdio.h>
#include <math.h>
#include <string.h>
#include <stdbool.h>
#include <stdlib.h>  // Añadido para 'atol'

#define MAX_DIGITOS 4

// Función para contar los dígitos de un número
int contar_digitos(int N) {
    if (N == 0)
        return 1;
    return (int)log10(N) + 1;
}

// Función para validar los tres números
bool validar_numeros(int a, int b, int c) {
    // Verificar que sean naturales
    if (a <= 0 || b <= 0 || c <= 0)
        return false;
    // Verificar que sean distintos
    if (a == b || a == c || b == c)
        return false;
    // Verificar que tengan máximo 4 dígitos
    if (contar_digitos(a) > MAX_DIGITOS || contar_digitos(b) > MAX_DIGITOS || contar_digitos(c) > MAX_DIGITOS)
        return false;
    return true;
}

// Función para verificar si un número es Sastry
int es_sastry(int N) {
    // Concatenar N y N+1
    int siguiente = N + 1;
    char concatenado_str[20];
    sprintf(concatenado_str, "%d%d", N, siguiente);
    long concatenado = atol(concatenado_str);
    
    // Calcular la raíz cuadrada
    double raiz = sqrt((double)concatenado);
    long parte_entera = (long)floor(raiz);
    
    if (parte_entera * parte_entera == concatenado)
        return 1;
    else
        return 0;
}

// Función para verificar si un número es Apocalíptico
int es_apocaliptico(int N) {
    char num_str[10];
    sprintf(num_str, "%d", N);
    if (strstr(num_str, "666") != NULL)
        return 1;
    else
        return 0;
}

int main() {
    int num1, num2, num3;
    
    // Removidos los prompts para facilitar la evaluación automática
    scanf("%d", &num1);
    scanf("%d", &num2);
    scanf("%d", &num3);
    
    // Validar los números
    bool validacion = validar_numeros(num1, num2, num3);
    if (!validacion) {
        printf("Por lo menos uno de los datos de entrada no es correcto.\n");
        return 0;
    }
    
    // Ordenar los números de manera descendente
    int numeros[3] = {num1, num2, num3};
    // Ordenamiento simple
    for(int i=0; i<3; i++) {
        for(int j=i+1; j<3; j++) {
            if(numeros[j] > numeros[i]) {
                int temp = numeros[i];
                numeros[i] = numeros[j];
                numeros[j] = temp;
            }
        }
    }
    
    // printf("Numeros ordenados de manera descendente: %d, %d, %d\n", numeros[0], numeros[1], numeros[2]);
    
    // Evaluar cada número
    for(int i=0; i<3; i++) {
        int actual = numeros[i];
        int sastry = es_sastry(actual);
        int apocaliptico = es_apocaliptico(actual);
        if (i == 0)
            printf("Numero mayor: %d.\n", actual);
        else if (i == 1)
            printf("Numero intermedio: %d.\n", actual);
        else
            printf("Numero menor: %d.\n", actual);
        printf("- Es Sastry: %d\n", sastry);
        printf("- Es Apocaliptico:%d\n", apocaliptico);
    }
    
    return 0;
}
