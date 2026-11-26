from machine import Pin, ADC
import time, onewire, ds18x20
import network
import urequests

# =============================================================
# Configuración de Red y Ubidots (Con tus datos reales)
# =============================================================
WIFI_SSID = "Aaa no hermano consigue la tuya"
WIFI_PASS = "12345678"

UBIDOTS_TOKEN = "BBUS-AFcbyi3UoUeF8ygEfgewvdeHTunKgf"  # Tu token de Ubidots
DEVICE_LABEL = "cultivo-hidroponico"                     # Nombre de tu dispositivo en la nube

# =============================================================
# Configuración de Pines (Hardware de tu proyecto)
# =============================================================
ds = ds18x20.DS18X20(onewire.OneWire(Pin(16)))  # DS18B20 en GP16
tds_vcc = Pin(22, Pin.OUT, value=0)             # Alimentación TDS en GP22
adc_tds = ADC(Pin(26))                          # Señal TDS en GP26
adc_ph = ADC(Pin(27))                           # Señal pH en GP27
boya = Pin(15, Pin.IN, Pin.PULL_UP)             # Boya en GP15
bomba = Pin(14, Pin.OUT, value=0)               # Bomba (MOSFET) en GP14

# =============================================================
# Funciones de Conexión Wi-Fi
# =============================================================
def conectar_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if wlan.isconnected():
        print("Ya estabas conectado. IP:", wlan.ifconfig()[0])
        return True

    print(f"Conectando a la red '{ssid}'...")
    wlan.connect(ssid, password)
    
    intentos = 0
    while not wlan.isconnected() and intentos < 30: 
        time.sleep(0.5)
        print(".", end="")
        intentos += 1

    if wlan.isconnected():
        print("\n¡Conexión exitosa! IP local:", wlan.ifconfig()[0])
        return True
    else:
        print(f"\nError: No se pudo conectar a la red. Estado: {wlan.status()}")
        return False

# =============================================================
# Funciones de Lectura de Sensores
# =============================================================
def leer_voltaje(adc):
    s = 0
    for _ in range(20):
        s += adc.read_u16()
        time.sleep_ms(5)
    return (s / 20) * 3.3 / 65535

def leer_sensores():
    # 1. Temperatura DS18B20
    temp = 25.0
    try:
        sensores = ds.scan()
        if sensores:
            ds.convert_temp()
            time.sleep_ms(750)
            temp = round(ds.read_temp(sensores[0]), 2)
    except Exception as e:
        print("Error leyendo temperatura:", e)

    # 2. TDS
    tds_vcc.value(1)
    time.sleep_ms(300)
    v_tds = leer_voltaje(adc_tds)
    tds_vcc.value(0)
    v_comp = v_tds / (1 + 0.02 * (temp - 25))
    tds = round((133.42 * v_comp**3 - 255.86 * v_comp**2 + 857.39 * v_comp) * 0.5, 1)
    if tds < 0: tds = 0

    # 3. pH (Conversión de voltaje Po)
    v_nodo = leer_voltaje(adc_ph)
    v_po = v_nodo * 1.5
    ph = round(7.0 + ((2.5 - v_po) / 0.18), 2)

    # 4. Boya (1 = Abierta/Nivel bajo, 0 = Cerrada/Nivel OK)
    estado_boya = 1 if boya.value() == 1 else 0

    # 5. Estado de la Bomba (0 o 1)
    estado_bomba = bomba.value()

    return temp, tds, ph, estado_boya, estado_bomba

# =============================================================
# Función de Envío a Ubidots (Usando HTTP)
# =============================================================
def enviar_a_ubidots(temp, tds, ph, boya_val, bomba_val):
    url = f"http://industrial.api.ubidots.com/api/v1.6/devices/{DEVICE_LABEL}"
    headers = {
        "X-Auth-Token": UBIDOTS_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "temperatura": temp,
        "tds": tds,
        "ph": ph,
        "nivel_agua": boya_val,
        "bomba": bomba_val
    }

    print(f"Enviando -> Temp: {temp}°C | TDS: {tds}ppm | pH: {ph} | Boya: {boya_val} | Bomba: {bomba_val}")

    try:
        res = urequests.post(url, json=payload, headers=headers)
        print("¡Código de respuesta de Ubidots:", res.status_code, "!")
        print("Respuesta:", res.text)
        res.close()
        print("¡Enviado exitosamente!\n")
        return True
    except Exception as e:
        print("Error al enviar a Ubidots:", e, "\n")
        return False

# =============================================================
# Flujo Principal del Programa
# =============================================================
print("--- Iniciando sistema IoT Cultivo Hidropónico ---")

if conectar_wifi(WIFI_SSID, WIFI_PASS):
    print("\n--- Entrando al bucle de telemetría (Ubidots) ---")
    
    while True:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.isconnected():
            print("Conexión Wi-Fi perdida. Reconectando...")
            conectar_wifi(WIFI_SSID, WIFI_PASS)
        
        # Lee sensores físicos
        t, td, p, b, bm = leer_sensores()
        
        # Envía a Ubidots
        enviar_a_ubidots(t, td, p, b, bm)
        
        # Pausa de 10 segundos para respetar el límite de la API gratuita
        time.sleep(10)
else:
    print("No se pudo conectar al Wi-Fi. Revisa que tu red sea de 2.4 GHz.")