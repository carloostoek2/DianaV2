# Playbook de sabotaje (prueba de que la prueba sirve)

Hacerlo en una copia / rama; nunca en producción. Tras cada sabotaje, la prueba E2 **debe fallar**. Revertir siempre.

| Sabotaje | Cómo | Detecta |
|---|---|---|
| S1 Desconectar dependencia | En el test, pasar `None` (o quitar la línea en `composition.py`) para esa dependencia | Cableado ausente / pieza opcional que se omite sin ruido |
| S2 Apagar bandera | `feature_x=False` donde el contrato dice que debe estar ON | Que el efecto realmente dependa de esa bandera |
| S3 Romper la pieza | Hacer que el método lance `RuntimeError` | `except Exception` que oculta el fallo; la prueba debe ver rastro |
| S4 Vaciar el resultado | Hacer que el método devuelva `[]`, `None`, vector de ceros | Efecto "de relleno" aceptado como válido |
| S5 Cortar el llamador | Comentar la llamada en el orquestador/handler | Función huérfana que sigue pasando sus unitarias |
| S6 Cambiar el orden | Mover el hook antes de que exista el dato | Dependencias de orden (ej. leer traza antes de escribirla) |

Criterio: si ningún sabotaje hace fallar la prueba → la prueba es decorativa → ⚪ hasta reescribirla.
Registrar en el contrato: sabotaje aplicado + salida del test fallido.
