# ¿Por qué este modelo de IA? (decisión y justificación)

Pediste que eligiera el modelo que considero correcto y explicara por qué. Esta es la decisión completa, en cuatro pasos. Lo mismo está en el documento IEEE, en la **Sección V. Estrategia de Análisis de Datos e IA**.

---

## Decisión 1 — El "estado" del consumo **no** debe hacerlo la IA

**Antes:** entrenábamos un Random Forest para clasificar NORMAL / CONSUMO_ALTO / SOBRECARGA / VOLTAJE_ANOMALO.

**Problema:** esos estados **son reglas** que nosotros mismos programamos (por ejemplo, potencia ≥ 2500 W → sobrecarga). Un modelo que aprende a copiar una regla:
- es **redundante**: saca ~100 % porque copia la regla; no aprende nada nuevo;
- es **más riesgoso**: podría equivocarse justo en un caso crítico de seguridad;
- **depende de internet**: la alerta llegaría tarde si se cae la conexión.

**Decisión:** los estados se quedan como **reglas en el ESP32**, que actúa en milisegundos aunque no haya internet. Así se diseñan los sistemas de seguridad eléctrica reales.

**Verificación:** un Árbol de Decisión entrenado solo con los datos "redescubre" los umbrales que programamos. Eso demuestra que los datos son coherentes. Ver la sección 4 del notebook.

> **Frase para el pitch:** "No usamos IA para lo que una regla resuelve mejor. Las alertas de seguridad son reglas en el ESP32, porque deben ser instantáneas y funcionar sin internet."

---

## Decisión 2 — La IA se usa donde **sí** aporta: reconocer el aparato

**Problema real:** el usuario quiere saber **qué aparato** le está subiendo el recibo. El microondas (1200 W), la plancha (1100 W) y el aire acondicionado (1300 W) consumen casi lo mismo. Con el ruido normal de la medición, **un umbral de potencia no los separa**.

**Lo que sí los separa es su "huella eléctrica":**

| Aparato | Potencia | Factor de potencia | Por qué |
|---|---|---|---|
| Plancha, olla, secadora | 700–1600 W | ≈ 1.00 | Son resistencias: toda la energía se convierte en calor |
| Microondas | 1200 W | ≈ 0.92 | Fuente electrónica |
| Aire acondicionado | 1300 W | ≈ 0.85 | Motor: consume potencia reactiva |
| Refrigeradora | 150 W | ≈ 0.80 | Motor (compresor) |
| Televisor | 120 W | ≈ 0.95 | Fuente electrónica |

El modelo combina **7 variables**: potencia, corriente, voltaje, potencia aparente, factor de potencia, potencia reactiva y cambio de potencia (ΔP). Así aprende patrones que ninguna regla simple captura.

A esto se le llama **monitoreo no intrusivo de cargas (NILM)**: saber qué está encendido midiendo **solo en la entrada de la casa**, sin poner un sensor en cada aparato.

> **Frase para el pitch:** "La IA resuelve lo que una regla no puede: reconocer qué aparato está consumiendo usando su huella eléctrica."

---

## Decisión 3 — El algoritmo se elige **por evidencia**, no a dedo

En vez de decir "usamos Random Forest porque sí", **comparamos 8 algoritmos** con exactamente el mismo protocolo:

| Algoritmo | Idea en una línea |
|---|---|
| Línea base | Siempre adivina el aparato más común (sirve para saber si los demás aprenden algo) |
| Regresión logística | Fronteras rectas entre clases |
| k vecinos más cercanos | "Te pareces a tus vecinos" |
| SVM (kernel RBF) | Fronteras curvas con márgenes máximos |
| Árbol de Decisión | Preguntas sí/no en cadena |
| **Random Forest** | Muchos árboles con datos al azar que votan |
| Extra Trees | Como Random Forest pero con cortes aún más aleatorios |
| Gradient Boosting | Árboles en serie; cada uno corrige al anterior |

**Regla fijada antes de ver resultados** (para no hacer trampa):
> Se elige el modelo con **mayor F1 macro**. Si otro está a menos de 0.01 y es **más explicable**, se prefiere ese.

**¿Por qué F1 macro y no solo exactitud?** Si el 30 % de los datos son "refrigeradora", un modelo que siempre dice "refrigeradora" ya tiene 30 % de exactitud sin aprender nada. El F1 macro promedia el desempeño **por aparato**, así que un error en un aparato poco frecuente pesa igual.

### Resultado de la comparación (datos reales del proyecto)

Se usaron **303 lecturas con etiqueta de aparato, agrupadas en 93 episodios**. El 80 % de los episodios (246 lecturas) se usó para comparar los modelos, con validación cruzada agrupada de 5 particiones:

| Modelo | F1 macro (promedio ± desv.) | Exactitud |
|---|---|---|
| **Random Forest** | **0.885 ± 0.055** | 0.898 |
| Extra Trees | 0.874 ± 0.077 | 0.906 |
| Gradient Boosting (Hist) | 0.826 ± 0.055 | 0.849 |
| Árbol de Decisión | 0.808 ± 0.066 | 0.824 |
| Regresión logística | 0.796 ± 0.078 | 0.825 |
| SVM (kernel RBF) | 0.750 ± 0.075 | 0.793 |
| k vecinos (k=5) | 0.731 ± 0.036 | 0.801 |
| Línea base | 0.051 ± 0.005 | 0.256 |

**Ganó Random Forest.** Extra Trees quedó a 0.011, fuera del margen de empate (0.01), y además es menos explicable. Así que, según la regla fijada de antemano, **el modelo elegido es Random Forest**. No se eligió "porque sí": ganó la comparación.

Todos los modelos superan por mucho a la línea base (0.05). Eso confirma que las variables eléctricas **sí** contienen información sobre el aparato.

---

## Decisión 4 — Validar **sin hacer trampa** (por episodios)

**El error común:** repartir las lecturas al azar entre entrenamiento (80 %) y prueba (20 %).

**Por qué es trampa aquí:** cuando el aire acondicionado está encendido, se generan ~10 lecturas seguidas casi idénticas. Si 8 caen en entrenamiento y 2 en prueba, el modelo "reconoce" las 2 de prueba porque **ya vio casi las mismas**. La exactitud sale inflada y en la vida real fallaría.

**Lo correcto:** agrupar las lecturas en **episodios** (cada vez que un aparato se enciende hasta que cambia) y que cada episodio quede **completo** en entrenamiento **o** en prueba (`StratifiedGroupKFold`). Así la prueba mide si el modelo reconoce un **encendido nuevo** que nunca vio, que es lo que pasará en una casa real.

Además:
- El 20 % de los episodios se apartó **al inicio** y no se tocó hasta la evaluación final.
- Con el 80 % restante se compararon los modelos y se ajustaron los hiperparámetros (`GridSearchCV`) con validación cruzada de 5 particiones.

### Resultado final (episodios que el modelo nunca vio)

- Ajuste de hiperparámetros (GridSearchCV): 500 árboles, sin límite de profundidad, `max_features = sqrt`, `min_samples_leaf = 1`. El F1 macro en validación cruzada subió a **0.891**.
- **Prueba final con 57 lecturas de episodios nunca vistos: exactitud 0.930 y F1 macro 0.918.**
- Aparatos reconocidos sin errores: refrigeradora, televisor, microondas y consumo base.
- Errores principales: la **secadora de pelo** (1600 W, resistiva) se confundió 2 veces con el aire acondicionado y 1 vez con la plancha. Tiene sentido: cuando la secadora se enciende junto con otros aparatos, la potencia total se parece.
- **Variables más importantes** (importancia por permutación): **potencia reactiva (0.128)**, **factor de potencia (0.091)** y potencia activa (0.086). Esto confirma la idea central: **la huella eléctrica (reactiva y factor de potencia) aporta más que la potencia sola.**

> **Frase para el pitch:** "Comparamos 8 modelos y ganó Random Forest, con F1 macro de 0.89 en validación y 0.92 en episodios que nunca vio. La variable más importante fue la potencia reactiva: el modelo distingue los aparatos por su huella eléctrica, no solo por cuánto consumen."

---

## ¿Y por qué no una red neuronal o Teachable Machine?

- **Teachable Machine** trabaja con imágenes, sonidos o posturas. Nuestros datos son números en una tabla.
- **Una red neuronal** necesita miles de ejemplos y es una "caja negra". Con unos cientos de lecturas y 7 variables, los modelos de árboles igualan o superan a una red neuronal y además **explican** qué variable usaron (ver la importancia por permutación).

## Limitación honesta (dila si te preguntan)

Los datos vienen de una **simulación** con huellas eléctricas típicas. En una casa real habrá más ruido y más aparatos encendidos a la vez, así que el desempeño bajará. Por eso el siguiente paso es **reentrenar con datos reales** del prototipo físico (ZMPT101B + SCT-013 o PZEM-004T). El procedimiento ya está listo en el notebook: solo cambia la fuente de datos.
