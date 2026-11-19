# =====================================================================
#  CULTIVO HIDROPÓNICO URBANO — Raspberry Pi Pico 2 W (MicroPython)
#  Todo en un solo archivo. Guárdenlo en la Pico como main.py
# =====================================================================

# ---------------------------------------------------------------------
# 1. QUÉ HACE EL PROGRAMA: cambien MODO y presionen ▶ en Thonny
#    "prueba_bomba"      -> prueba la bomba y muestra el valor de la boya
#    "prueba_sensores"   -> muestra temperatura, TDS/EC y pH cada 3 s
#    "calibrar_ph"       -> calibra el pH con los buffers
#    "reto_sondeo"       -> reto, versión ANTES (sondeo)
#    "reto_interrupcion" -> reto, versión DESPUÉS (interrupción)
#    "normal"            -> funcionamiento final con Ubidots (déjenlo así al terminar)
# ---------------------------------------------------------------------
MODO = "prueba_bomba"

# ---------------------------------------------------------------------
# 2. AJUSTES (editen solo esta parte)
# ---------------------------------------------------------------------
WIFI_SSID = "NOMBRE_DE_SU_RED"
WIFI_PASS = "CLAVE_DE_SU_RED"
UBIDOTS_TOKEN = "PEGAR_SU_TOKEN"            # Ubidots > Mi perfil > API Credentials
UBIDOTS_DEVICE = "hidroponico"
UBIDOTS_URL = "https://industrial.api.ubidots.com/api/v1.6/devices/"
INTERVALO_S = 15 * 60                       # cada cuánto se mide y se envía

BOYA_AGUA_BAJA = 1          # valor de la boya con agua baja (lo ven en "prueba_bomba")

PH_BUFFER_NEUTRO = 7.00     # pongan 6.86 si su sobre de buffer dice 6.86
PH_BUFFER_ACIDO = 4.00
PH_V_NEUTRO = 1.667         # lo llena el modo "calibrar_ph"
PH_V_ACIDO = 2.030          # lo llena el modo "calibrar_ph"

REPETICIONES_RETO = 20

# =====================================================================
#  De aquí para abajo no hace falta cambiar nada
# =====================================================================
from machine import Pin, ADC
import time
import network
import onewire
import ds18x20
try:
    import requests
except ImportError:
    import urequests as requests

# ---------- Pines (los mismos del manual) ----------
bomba = Pin(14, Pin.OUT, value=0)                  # GP14 -> SIG del MOSFET
boya = Pin(15, Pin.IN, Pin.PULL_UP)                # GP15 -> boya (otro cable a GND)
ds = ds18x20.DS18X20(onewire.OneWire(Pin(16)))     # GP16 -> DS18B20 (4.7 kΩ a 3.3 V)
tds_adc = ADC(Pin(26))                             # GP26 -> A del TDS
ph_adc = ADC(Pin(27))                              # GP27 -> nodo del divisor 10k/20k
try:
    tds_vcc = Pin(22, Pin.OUT, value=0, drive=Pin.DRIVE_3)   # GP22 -> + del TDS
except (AttributeError, TypeError, ValueError):
    tds_vcc = Pin(22, Pin.OUT, value=0)

# ---------- Sensores ----------
def agua_baja():
    return boya.value() == BOYA_AGUA_BAJA


def voltaje(adc, n=40):
    vals = sorted(adc.read_u16() for _ in range(n))
    util = vals[8:-8]
    return sum(util) / len(util) * 3.3 / 65535


def temperatura():
    roms = ds.scan()
    if not roms:
        raise OSError("No se encuentra el DS18B20: revisen GP16 y la resistencia de 4.7 kΩ")
    ds.convert_temp()
    time.sleep_ms(750)
    return ds.read_temp(roms[0])


def tds_ppm(t):
    tds_vcc.on()
    time.sleep(1)
    v = voltaje(tds_adc)
    tds_vcc.off()                                  # apagado para no interferir con el pH
    v25 = v / (1.0 + 0.02 * (t - 25.0))
    ppm = (133.42 * v25 ** 3 - 255.86 * v25 ** 2 + 857.39 * v25) * 0.5
    return max(0.0, ppm), v


def voltaje_ph():
    estado = bomba.value()
    bomba.off()                                    # sin ruido de la bomba
    tds_vcc.off()
    time.sleep(2)
    v = voltaje(ph_adc)
    bomba.value(estado)
    return v


def leer_ph():
    v = voltaje_ph()
    pendiente = (PH_BUFFER_NEUTRO - PH_BUFFER_ACIDO) / (PH_V_NEUTRO - PH_V_ACIDO)
    return PH_BUFFER_NEUTRO + (v - PH_V_NEUTRO) * pendiente, v

# ---------- Ubidots ----------
def conectar_wifi(timeout_s=20):
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if not w.isconnected():
        w.connect(WIFI_SSID, WIFI_PASS)
        t0 = time.time()
        while not w.isconnected() and time.time() - t0 < timeout_s:
            time.sleep(0.5)
    return w.isconnected()


def enviar(datos):
    try:
        r = requests.post(UBIDOTS_URL + UBIDOTS_DEVICE + "/", json=datos,
                          headers={"X-Auth-Token": UBIDOTS_TOKEN, "Content-Type": "application/json"})
        ok = r.status_code in (200, 201)
        if not ok:
            print("Ubidots respondió", r.status_code, r.text)
        r.close()
        return ok
    except Exception as e:
        print("No se pudo enviar a Ubidots:", e)
        return False

# ---------- Interrupción de la boya ----------
t_cambio = 0
t_apagado = 0
evento = False
APAGAR_EN_IRQ = MODO in ("normal", "reto_interrupcion")


def boya_irq(pin):
    global t_cambio, t_apagado, evento
    if pin.value() == BOYA_AGUA_BAJA:
        t_cambio = time.ticks_us()
        if APAGAR_EN_IRQ:
            bomba.value(0)                         # la interrupción apaga la bomba al instante
            t_apagado = time.ticks_us()
        evento = True


boya.irq(trigger=Pin.IRQ_RISING if BOYA_AGUA_BAJA == 1 else Pin.IRQ_FALLING,
         handler=boya_irq, hard=True)

# =====================================================================
#  MODOS
# =====================================================================
def prueba_bomba():
    print("Bomba: 3 encendidos de 2 s (póngala en un vaso con agua)")
    for _ in range(3):
        bomba.on(); time.sleep(2); bomba.off(); time.sleep(1)
    print("Suban y bajen el flotador. Anoten el valor con el flotador ABAJO -> BOYA_AGUA_BAJA")
    anterior = None
    while True:
        v = boya.value()
        if v != anterior:
            print("boya =", v)
            anterior = v
        time.sleep(0.1)


def prueba_sensores():
    while True:
        t = temperatura()
        ppm, v_tds = tds_ppm(t)
        ph, v_ph = leer_ph()
        print("T = %.1f °C | TDS = %.0f ppm (EC %.2f mS/cm) | pH = %.2f (%.3f V)" % (t, ppm, ppm / 500, ph, v_ph))
        time.sleep(3)


def calibrar_ph():
    print("Antes ajusten el cero del PH-4502C a 2.50 V (paso 13 del manual)")
    def medir(nombre):
        input("\nSonda enjuagada en el buffer %s. Presionen Enter..." % nombre)
        vals = []
        for _ in range(30):
            v = voltaje_ph()
            vals.append(v)
            print("  %.4f V" % v)
        return sum(vals[-10:]) / 10
    v_n = medir("NEUTRO (%.2f)" % PH_BUFFER_NEUTRO)
    v_a = medir("ÁCIDO (%.2f)" % PH_BUFFER_ACIDO)
    print("\nCopien estas líneas en la parte de AJUSTES:")
    print("PH_V_NEUTRO = %.3f" % v_n)
    print("PH_V_ACIDO = %.3f" % v_a)
    if v_a <= v_n:
        print("Atención: el voltaje ácido debería ser MAYOR que el neutro. Revisen la sonda y el divisor.")


def reto(modo_sondeo):
    global evento, t_apagado
    nombre = "sondeo" if modo_sondeo else "interrupcion"
    lat = []
    print("Reto (%s): bajen el flotador %d veces" % (nombre, REPETICIONES_RETO))
    while len(lat) < REPETICIONES_RETO:
        while agua_baja():
            time.sleep_ms(50)
        bomba.on()
        evento = False
        if modo_sondeo:
            while True:                            # bucle típico: primero mide, después revisa la boya
                voltaje_ph()
                if agua_baja():
                    bomba.off()
                    t_apagado = time.ticks_us()
                    break
        while not evento:
            time.sleep_ms(1)
        d = time.ticks_diff(t_apagado, t_cambio)
        lat.append(d)
        print("%2d) bomba apagada %.3f ms después de bajar la boya" % (len(lat), d / 1000))
    print("\n%s: promedio %.3f ms | máximo %.3f ms" % (nombre, sum(lat) / len(lat) / 1000, max(lat) / 1000))
    with open("reto_%s.csv" % nombre, "w") as f:
        f.write("repeticion,latencia_us\n")
        for i, d in enumerate(lat, 1):
            f.write("%d,%d\n" % (i, d))
    print("Guardado en reto_%s.csv (en la Pico)" % nombre)


def normal():
    global evento
    ultimo = time.time() - INTERVALO_S
    while True:
        if not agua_baja() and not bomba.value():   # vuelve a encender si el agua lleva 5 s bien
            time.sleep(5)
            if not agua_baja():
                bomba.on()
                print("Agua en buen nivel: bomba encendida")
        if evento:
            evento = False
            print("¡Agua baja! La interrupción apagó la bomba")
            ultimo = 0                              # enviar ya, para que salte la alerta en Ubidots
        if time.time() - ultimo >= INTERVALO_S:
            try:
                t = temperatura()
                ppm, _ = tds_ppm(t)
                ph, _ = leer_ph()
                datos = {"ph": round(ph, 2), "tds": round(ppm), "ec": round(ppm / 500, 2),
                         "temperatura": round(t, 1), "boya": 0 if agua_baja() else 1,
                         "bomba": bomba.value()}
                print(datos)
                if conectar_wifi():
                    enviar(datos)
                else:
                    print("Sin Wi-Fi: no se envió esta medición")
            except Exception as e:
                print("Error al medir:", e)
            ultimo = time.time()
        time.sleep(0.2)


try:
    if MODO == "prueba_bomba":
        prueba_bomba()
    elif MODO == "prueba_sensores":
        prueba_sensores()
    elif MODO == "calibrar_ph":
        calibrar_ph()
    elif MODO == "reto_sondeo":
        reto(True)
    elif MODO == "reto_interrupcion":
        reto(False)
    else:
        normal()
finally:
    bomba.off()          # al detener el programa, la bomba siempre queda apagada
