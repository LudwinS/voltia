# VoltIA - Monitor inteligente de consumo eléctrico doméstico
# ESP32 (MicroPython, Wokwi) -> MQTT -> Adafruit IO -> IA (Random Forest) + Telegram
#
# Simulación de sensores (Wokwi no incluye ZMPT101B / SCT-013 / PZEM-004T):
#   - Potenciómetro "Carga"   (GPIO34): demanda de la vivienda 0 - 3500 W
#   - Potenciómetro "Voltaje" (GPIO35): tensión de la red 90 - 150 V
#   - Interruptor deslizante  (GPIO15): AUTO (perfil de consumo simulado) / MANUAL (potenciómetros)
# Indicadores locales: LED verde/amarillo/rojo, buzzer y pantalla OLED SSD1306.

import network
import time
import random
import math
import urequests
from machine import Pin, ADC, PWM, I2C
from umqtt.simple import MQTTClient
import ssd1306

# ------------------------------------------------------------------
# 1. CREDENCIALES: reemplaza los marcadores al ejecutar; nunca subas tus claves
# ------------------------------------------------------------------
AIO_USER = "Ludwin1611"
AIO_KEY = "TU_AIO_KEY"
TG_TOKEN = "TU_TOKEN_DE_BOTFATHER"     # vacío "" para desactivar Telegram
TG_CHAT_ID = "TU_CHAT_ID"

AIO_SERVER = "io.adafruit.com"
AIO_PORT = 1883
FEEDS = ("voltaje", "corriente", "potencia", "energia", "estado", "aparato")
FEED_UMBRAL = AIO_USER + "/feeds/umbral-potencia"

# ------------------------------------------------------------------
# 2. PARÁMETROS DEL SISTEMA
# ------------------------------------------------------------------
INTERVALO_S = 15          # 6 feeds cada 15 s = 24 datos/min (límite gratuito: 30/min)
V_NOMINAL = 120.0         # tensión residencial en El Salvador
V_MIN, V_MAX = 108.0, 132.0   # +-10 % del nominal
P_SOBRECARGA = 2500.0     # W
I_SOBRECARGA = 20.0       # A
umbral_alto = 1500.0      # W, ajustable desde el slider del dashboard
COOLDOWN_TG_S = 60        # anti-spam de Telegram

# ------------------------------------------------------------------
# 3. HARDWARE
# ------------------------------------------------------------------
pot_carga = ADC(Pin(34))
pot_carga.atten(ADC.ATTN_11DB)
pot_volt = ADC(Pin(35))
pot_volt.atten(ADC.ATTN_11DB)
modo_sw = Pin(15, Pin.IN, Pin.PULL_DOWN)

led_verde = Pin(2, Pin.OUT)
led_amarillo = Pin(4, Pin.OUT)
led_rojo = Pin(5, Pin.OUT)
buzzer = PWM(Pin(18), freq=2000, duty=0)

oled = ssd1306.SSD1306_I2C(128, 64, I2C(0, scl=Pin(22), sda=Pin(21)))


def pantalla(*lineas):
    oled.fill(0)
    for i, txt in enumerate(lineas):
        oled.text(txt, 0, i * 11)
    oled.show()


# ------------------------------------------------------------------
# 4. MODELO DE CONSUMO (modo AUTO)
#    Carga base de una vivienda + electrodomésticos que se encienden al azar
# ------------------------------------------------------------------
ELECTRODOMESTICOS = (
    # (nombre, potencia W, factor de potencia, prob. de encender por lectura, lecturas encendido)
    # Cada aparato tiene una "huella" distinta: los resistivos (plancha, olla, secadora)
    # tienen fp ~1.0; los de motor (refrigeradora, aire) consumen potencia reactiva.
    ("Refrigeradora", 150, 0.80, 0.30, 8),
    ("Televisor", 120, 0.95, 0.10, 12),
    ("Microondas", 1200, 0.92, 0.06, 3),
    ("Plancha", 1100, 1.00, 0.05, 6),
    ("Aire acondicionado", 1300, 0.85, 0.05, 10),
    ("Olla arrocera", 700, 1.00, 0.05, 5),
    ("Secadora de pelo", 1600, 0.99, 0.04, 3),
)
activos = {}   # nombre -> lecturas restantes


def reactiva(p, fp):
    return p * math.tan(math.acos(fp))


def perfil_auto():
    # Carga base: iluminación, router y cargadores
    p_base = 80 + random.uniform(-10, 25)
    p_tot, q_tot = p_base, reactiva(p_base, 0.90)
    principal, p_principal = "Base", 0
    for nombre, watts, fp, prob, duracion in ELECTRODOMESTICOS:
        if nombre in activos:
            activos[nombre] -= 1
            if activos[nombre] <= 0:
                del activos[nombre]
        elif random.random() < prob:
            activos[nombre] = duracion
        if nombre in activos:
            p = watts * random.uniform(0.95, 1.04)
            p_tot += p
            q_tot += reactiva(p, max(0.5, min(1.0, fp + random.uniform(-0.02, 0.02))))
            if p > p_principal:
                principal, p_principal = nombre, p
    v = V_NOMINAL + random.uniform(-2.5, 2.5)
    r = random.random()
    if r < 0.04:
        v = random.uniform(96, 107)            # caída de tensión
    elif r < 0.07:
        v = random.uniform(133, 140)           # sobretensión
    return v, p_tot, q_tot, principal


def perfil_manual():
    p = pot_carga.read() / 4095 * 3500
    v = 90 + pot_volt.read() / 4095 * 60
    return v + random.uniform(-0.5, 0.5), p, reactiva(p, 0.95), "Manual"


def medir():
    v, p, q, aparato = perfil_manual() if modo_sw.value() else perfil_auto()
    s = math.sqrt(p * p + q * q)               # potencia aparente (VA)
    i = s / v if s > 0 else 0.0                # corriente RMS
    return round(v, 1), round(i, 2), round(p, 1), aparato


def clasificar(v, i, p):
    if v < V_MIN or v > V_MAX:
        return "VOLTAJE_ANOMALO"
    if p >= P_SOBRECARGA or i >= I_SOBRECARGA:
        return "SOBRECARGA"
    if p >= umbral_alto:
        return "CONSUMO_ALTO"
    return "NORMAL"


def indicadores(estado):
    led_verde.value(estado == "NORMAL")
    led_amarillo.value(estado == "CONSUMO_ALTO")
    led_rojo.value(estado in ("SOBRECARGA", "VOLTAJE_ANOMALO"))
    buzzer.duty(512 if estado in ("SOBRECARGA", "VOLTAJE_ANOMALO") else 0)


# ------------------------------------------------------------------
# 5. TELEGRAM
# ------------------------------------------------------------------
def url_encode(txt):
    seguro = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    out = ""
    for b in txt.encode("utf-8"):
        c = chr(b)
        out += c if c in seguro else "%{:02X}".format(b)
    return out


def telegram(msg):
    if not TG_TOKEN or TG_TOKEN.startswith("TU_"):
        return
    url = "https://api.telegram.org/bot{}/sendMessage?chat_id={}&text={}".format(
        TG_TOKEN, TG_CHAT_ID, url_encode(msg))
    try:
        r = urequests.get(url)
        r.close()
        print("Telegram enviado")
    except Exception as e:
        print("Error Telegram:", e)


MENSAJES = {
    "CONSUMO_ALTO": "Consumo alto: {p} W ({i} A). Revisa qué aparatos están encendidos.",
    "SOBRECARGA": "SOBRECARGA: {p} W / {i} A. Riesgo para el circuito, desconecta cargas.",
    "VOLTAJE_ANOMALO": "Voltaje fuera de rango: {v} V. Protege tus equipos.",
    "NORMAL": "Consumo normalizado: {p} W.",
}

# ------------------------------------------------------------------
# 6. CONEXIÓN WI-FI Y MQTT
# ------------------------------------------------------------------
pantalla("VoltIA", "Conectando WiFi")
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect("Wokwi-GUEST", "")
while not wifi.isconnected():
    time.sleep(0.3)
    print(".", end="")
print("\nWi-Fi conectado")


def al_recibir(topic, msg):
    global umbral_alto
    try:
        umbral_alto = float(msg.decode())
        print("Nuevo umbral de consumo alto desde la nube:", umbral_alto, "W")
    except ValueError:
        pass


cliente = MQTTClient("voltia-esp32-" + str(random.getrandbits(16)), AIO_SERVER,
                     AIO_PORT, AIO_USER, AIO_KEY, keepalive=60)
cliente.set_callback(al_recibir)
pantalla("VoltIA", "Conectando", "Adafruit IO")
cliente.connect()
cliente.subscribe(FEED_UMBRAL)
print("Conectado a Adafruit IO")


def publicar(feed, valor):
    cliente.publish("{}/feeds/{}".format(AIO_USER, feed), str(valor))


# ------------------------------------------------------------------
# 7. BUCLE PRINCIPAL
# ------------------------------------------------------------------
energia_kwh = 0.0
estado_prev = "NORMAL"
ultimo_tg = -COOLDOWN_TG_S
ultimo_envio = time.time() - INTERVALO_S
print("voltaje_V,corriente_A,potencia_W,energia_kWh,estado,aparato")

while True:
    try:
        cliente.check_msg()
    except OSError:
        cliente.connect()
        cliente.subscribe(FEED_UMBRAL)

    ahora = time.time()
    if ahora - ultimo_envio >= INTERVALO_S:
        dt = ahora - ultimo_envio
        ultimo_envio = ahora
        v, i, p, aparato = medir()
        energia_kwh += p * dt / 3600000
        estado = clasificar(v, i, p)
        indicadores(estado)
        pantalla("VoltIA " + ("MANUAL" if modo_sw.value() else "AUTO"),
                 "V: {} V".format(v), "I: {} A".format(i),
                 "P: {} W".format(p), "E: {:.4f} kWh".format(energia_kwh), estado[:16])

        for feed, valor in zip(FEEDS, (v, i, p, round(energia_kwh, 5), estado, aparato)):
            publicar(feed, valor)
        print("{},{},{},{:.5f},{},{}".format(v, i, p, energia_kwh, estado, aparato))

        # Solo se notifica cuando cambia el estado y respetando el anti-spam;
        # si el cooldown bloquea el aviso, se reintenta en la siguiente lectura.
        if estado != estado_prev and ahora - ultimo_tg >= COOLDOWN_TG_S:
            telegram(MENSAJES[estado].format(v=v, i=i, p=p))
            ultimo_tg = ahora
            estado_prev = estado

    time.sleep(0.2)
