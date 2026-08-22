# Acuerdo con el proveedor de IA — guía para la dueña

**Propósito:** que Diana envíe conversaciones de VIPs a un modelo externo con
una capa legal y una capa técnica de protección de datos. Esta guía explica
qué es el acuerdo, qué hay que pedir y qué hace el sistema por su cuenta.

**Fecha:** 2026-08-22 · **Proveedor actual:** DeepSeek (el sistema permite
cambiar de proveedor sin tocar el código — ver más abajo).

---

## 1. Qué es este acuerdo

Cuando Diana responde, un fragmento de la conversación viaja a los servidores
de la empresa del modelo (hoy, DeepSeek) para generar la respuesta. El acuerdo
con el proveedor (en la industria se llama *acuerdo de procesamiento de datos*
o DPA) es el **contrato legal** que establece qué puede y qué no puede hacer
esa empresa con la información que recibe.

**El masking (técnico) y el acuerdo (legal) se complementan:**

| Capa | Qué hace | Quién la activa |
| --- | --- | --- |
| **Masking de datos** | Antes de salir, se reemplazan correos, teléfonos, tarjetas, @usuarios y enlaces por marcadores genéricos. Ya implementado y activo. | La dueña (decisión de configuración, hoy encendido) |
| **Acuerdo con el proveedor** | Regula legalmente el resto de la información (nombres, conversaciones) que sí viaja. | La dueña firma/negocia con el proveedor |

El masking **no sustituye** al acuerdo: los nombres y el contenido de la
conversación siguen viajando (son necesarios para personalizar la respuesta),
y el acuerdo es lo que protege esa parte.

---

## 2. Qué hay que pedirle al proveedor (checklist)

Llevar esta lista al equipo comercial o de soporte de DeepSeek (o del
proveedor que se elija). Pedir respuestas **por escrito**:

1. **¿Dónde se procesan y guardan los datos?**
   DeepSeek opera servidores en China. Verificar si tu jurisdicción permite
   enviar datos de clientes ahí y qué implica para tu negocio.
2. **¿Por cuánto tiempo se retienen los mensajes?**
   Ideal: que se borren al terminar la generación de la respuesta, o un plazo
   corto y explícito.
3. **¿Se usan las conversaciones para entrenar sus modelos?**
   Exigir exclusión explícita (*opt-out*) o que nunca se usen para entrenar.
4. **¿Qué medidas de seguridad tienen?**
   Cifrado en tránsito y en reposo, controles de acceso, registro de accesos.
5. **¿Hay subprocesadores?** ¿Quiénes y para qué?
6. **¿Qué pasa ante una fuga de datos?**
   Plazo de notificación y responsabilidades.
7. **¿Cumplen alguna normativa?**
   Por ejemplo GDPR (Europa) u otras que apliquen a tu mercado.
8. **¿Pueden firmar un acuerdo de procesamiento de datos (DPA)?**
   Si no lo ofrecen estándar, es una señal de alerta.

---

## 3. Qué hace ya el sistema por su cuenta (sin depender del acuerdo)

- **Masking activo por defecto:** correos, teléfonos, tarjetas (validadas con
  checksum), @usuarios y enlaces salen enmascarados en **todas** las llamadas
  al modelo: análisis, generación, evaluación, memoria y perfiles.
- **El texto visible no cambia:** si el modelo repite un marcador en la
  respuesta, el sistema lo restaura al valor original antes de mostrarlo al
  VIP o guardarlo en la base. El VIP nunca ve "corchetes raros".
- **Sin datos en logs:** las estadísticas del masking se registran como
  conteos, nunca como contenido.
- **Proveedor intercambiable:** la arquitectura soporta cambiar de proveedor
  (hoy DeepSeek, con respaldo configurable a otro, p. ej. Anthropic). Si el
  acuerdo no es aceptable, se puede migrar sin reescribir el sistema.

---

## 4. Qué se queda fuera del masking (y por qué)

| Dato | ¿Se enmascara? | Motivo |
| --- | --- | --- |
| Correos, teléfonos, tarjetas, @usuarios, enlaces | Sí | Identificadores directos, detectables con precisión |
| Nombres propios | No | Son necesarios para personalizar (Diana usa el nombre del VIP) y un programa no distingue un nombre de una palabra normal |
| Direcciones, CURP/RFC, otros | No (versión 1) | Detección poco confiable; se puede ampliar en una versión futura con más patrones |

**Conclusión práctica:** el masking baja mucho el riesgo inmediato (lo que más
se filtra en mensajes son teléfonos y correos), y el acuerdo cubre el resto.
Hacer los dos es la posición segura.

---

## 5. Pasos siguientes (acciones de la dueña)

1. Contactar al equipo de DeepSeek (o decidir proveedor) pidiendo un DPA con
   la checklist de la sección 2.
2. Si la respuesta sobre China/retensión/entrenamiento no es aceptable,
   evaluar migrar de proveedor (el sistema está preparado).
3. Revisar con un abogado o asesor de privacidad el texto antes de firmar.
4. Guardar el acuerdo firmado junto a esta guía en la documentación del
   negocio.
