# Plantilla de contrato (una por archivo en audit/contracts/)

```
ID:            C-<AREA>-<NN>            (ej. C-SHADOW-01)
Promesa:       una frase, en lenguaje de negocio
Fuente:        doc + sección (ej. SPEC-AUTONOMIA-CALIBRACION §Fila 4)
Disparador:    qué evento real lo activa (mensaje VIP, aprobación de la dueña, job a las X)
Efecto:        qué debe quedar observable (tabla.columna, mensaje, métrica) y con qué valores
Banderas:      bandera → efecto esperado en ON / en OFF
Camino:        entrada → paso → paso → efecto   (con archivo:línea)
Puntos ciegos: dónde puede romperse en silencio
Prueba E2:     ruta del test + qué asierta
Sabotaje E3:   qué se desconectó y que la prueba falló (evidencia)
Vigilante E4:  consulta/chequeo en producción y umbral de alerta
Nivel:         E0 | E1 | E2 | E3 | E4
Semáforo:      🟢 🟡 🔴 ⚪
Hallazgos:     lista con evidencia
```
