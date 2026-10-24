# El dashboard de VoltIA en Adafruit IO

**Enlace público (solo lectura):** https://io.adafruit.com/Ludwin1611/dashboards/voltia-monitor-de-consumo
**Cuenta:** `Ludwin1611` (el slider de umbral solo lo controla el propietario).

## ¿Qué es un dashboard y qué es un feed?

- Un **feed** es una "columna" de datos en la nube. Cada vez que el ESP32 publica un valor, Adafruit IO lo guarda con su **fecha y hora** (`created_at`) durante 30 días. VoltIA usa 7 feeds:

| Feed | Qué guarda | Unidad | Quién lo escribe |
|---|---|---|---|
| `voltaje` | Tensión de la red | V | ESP32, cada 15 s |
| `corriente` | Corriente que consume la casa | A | ESP32, cada 15 s |
| `potencia` | Potencia activa (lo que se cobra) | W | ESP32, cada 15 s |
| `energia` | Energía acumulada desde que arrancó | kWh | ESP32, cada 15 s |
| `estado` | NORMAL / CONSUMO_ALTO / SOBRECARGA / VOLTAJE_ANOMALO | texto | ESP32, cada 15 s |
| `aparato` | Electrodoméstico que más consume en ese momento (etiqueta para la IA) | texto | ESP32, cada 15 s |
| `umbral-potencia` | Límite de "consumo alto" | W | **El dashboard** (slider) → el ESP32 lo lee |

- Un **dashboard** es la pantalla que muestra esos feeds con bloques visuales. Es la **réplica digital** del circuito: lo que pasa en el ESP32 se ve aquí en tiempo real.

## Los bloques, uno por uno

### 1. Voltaje de la red (medidor / gauge)
- Muestra el **último voltaje** recibido, en una escala de 90 a 150 V.
- Las marcas **108 V** y **132 V** son el rango aceptable: 120 V ± 10 %. Si la aguja sale de ese rango, el bloque cambia de color y el ESP32 marca `VOLTAJE_ANOMALO` (LED rojo, buzzer y aviso por Telegram).
- **Para qué sirve:** detectar caídas o subidas de tensión que dañan los electrodomésticos.

### 2. Potencia actual (medidor / gauge)
- Muestra los **vatios** que se consumen en ese instante, de 0 a 3500 W.
- La marca de **2500 W** es el límite de **sobrecarga**: por encima, el circuito de la casa corre riesgo y se dispara la alarma.
- **Para qué sirve:** ver de un vistazo si se está consumiendo poco, mucho o demasiado.

### 3. Historial de potencia (gráfico de líneas)
- Dibuja la potencia en el tiempo. Cada pico es un aparato que se encendió: un microondas da un pico corto, el aire acondicionado una "meseta" larga.
- **Para qué sirve:** ver los **patrones de consumo** (a qué hora se gasta más, cuánto dura cada aparato). Es lo que después analiza la IA.

### 4. Registro de estados y alertas (stream)
- Lista cada lectura con su hora y su estado. Es el **historial de eventos**: aquí queda constancia de cada sobrecarga o problema de voltaje.
- **Para qué sirve:** revisar qué pasó mientras no estabas viendo y servir de evidencia en la presentación.

### 5. Umbral de consumo alto (slider) — control bidireccional
- Es el único bloque que **envía** datos: al moverlo, publica un valor en el feed `umbral-potencia`. El ESP32 está **suscrito** a ese feed por MQTT, recibe el número al instante y cambia su regla de "consumo alto" (LED amarillo).
- Ejemplo: si lo bajas a 1000 W, cualquier consumo mayor a 1000 W enciende el LED amarillo.
- **Para qué sirve:** demuestra que la comunicación es en **dos sentidos** (nube → dispositivo). Es el concepto de **gemelo digital** que vieron en las clases 11 y 12.

### 6. Energía acumulada (texto)
- Muestra los **kWh** consumidos desde que arrancó el ESP32. Se calcula sumando potencia × tiempo en cada lectura: E = Σ P·Δt.
- **Para qué sirve:** es la misma unidad del recibo de luz. Multiplicando por la tarifa se estima cuánto se va a pagar.

### 7. Aparato detectado (texto)
- Muestra el nombre del electrodoméstico que **más consume** en ese momento (feed `aparato`): refrigeradora, televisor, microondas, plancha, aire acondicionado, olla arrocera, secadora de pelo, o "Base" si no hay ninguno grande encendido.
- En la simulación lo pone el perfil AUTO del ESP32. Es la **etiqueta** con la que se entrena la IA: el modelo aprende a adivinar este nombre usando solo las mediciones eléctricas.
- **Para qué sirve:** que el usuario sepa **qué aparato** le está subiendo el recibo. En la versión real, este dato lo daría el modelo de IA (no hay forma de que el medidor "sepa" qué está enchufado).

## Distribución en pantalla

Fila de arriba: voltaje, potencia, aparato detectado + energía, y el slider. Fila de abajo: historial de potencia (ancho) y registro de estados. En el celular, los bloques se apilan uno debajo del otro. La captura está en `dashboard_adafruit.png`.

## Cómo explicarlo en el pitch (≈ 40 segundos)

> "Todo lo que mide el ESP32 llega cada 15 segundos a Adafruit IO por MQTT. Aquí arriba vemos el voltaje y la potencia en tiempo real, con sus límites: 108 a 132 voltios y 2500 vatios para sobrecarga. Abajo, el historial de potencia muestra cada aparato que se enciende, y el registro guarda cada alerta. En este bloque vemos qué aparato domina el consumo, que es justo lo que aprende a reconocer nuestra IA. Además, el sistema es bidireccional: con este slider cambio desde la nube el umbral de consumo alto y el ESP32 lo aplica al instante. Y aquí vemos la energía acumulada en kWh, la misma unidad del recibo."

## Detalles técnicos que te pueden preguntar

- **Protocolo:** MQTT, puerto 1883, tópico `Ludwin1611/feeds/<feed>`. El ESP32 **publica** en 6 feeds y está **suscrito** a 1 (`umbral-potencia`).
- **Límite del plan gratuito:** 30 datos por minuto y 10 feeds. VoltIA envía 6 feeds cada 15 s, o sea 24 datos/min, y usa 7 feeds de los 10.
- **Almacenamiento:** 30 días de historial por feed. Se descarga como CSV o por la API REST, que es lo que usa el notebook de Colab para construir el dataset.
- **Por qué Adafruit IO y no una web propia:** es la plataforma del curso, el pitch pide mostrar los **feeds**, y ofrece gratis historial, dashboard, API y MQTT sin programar un servidor.
