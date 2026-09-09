# Viewifi Linux Host

Convierte una **Raspberry Pi, PC viejo o portátil con Linux** en un sensor de movimiento por WiFi, totalmente compatible con la app Android [Viewifi](https://github.com/pipe9494/viewifi): misma cuenta, mismo Telegram, mismo sistema multi-host.

> The Linux host turns a Raspberry Pi or any old Linux computer into a WiFi motion sensor — same engine, same Telegram alerts, same multi-host account as the Android app. *(English notes below.)*

---

## Cómo funciona

El movimiento de una persona altera las ondas WiFi. El host lee la potencia de señal (RSSI) de la red conectada ~4 veces por segundo y detecta perturbaciones con el mismo motor estadístico de la app:

- Baseline adaptativo EWMA que **solo aprende del estado calmado** (el movimiento no contamina el umbral)
- Test de spike con z-score sobre ventana corta (~3-6 s) + baselines por hora del día
- Debounce de 3 muestras + histéresis (sin falsas alarmas por rebotes de 1 s)
- Piso de 0.8 dBm (el RSSI viene cuantizado a enteros)

## Instalación (Raspberry Pi OS / Debian / Ubuntu)

### Opción A — Ejecutable descargable (recomendada, no requiere Python)

Descarga el binario para tu arquitectura desde [Releases](https://github.com/pipe9494/viewifi_linux/releases):

```bash
# PC / portátil / servidor (x86_64)
curl -LO https://github.com/pipe9494/viewifi_linux/releases/latest/download/viewifi-host-linux-x86_64

# Raspberry Pi 3/4/5 con OS de 64 bits (ARM64)
curl -LO https://github.com/pipe9494/viewifi_linux/releases/latest/download/viewifi-host-linux-arm64

chmod +x viewifi-host-linux-*
./viewifi-host-linux-x86_64          # arranca el host + panel web
```

### Opción B — Desde el código fuente

```bash
git clone https://github.com/pipe9494/viewifi_linux.git
cd viewifi_linux
sudo ./install.sh          # instala paquetes + servicio systemd
python3 -m viewifi.main --setup   # en /opt/viewifi, con tu usuario
sudo systemctl start viewifi-host@TU_USUARIO
journalctl -fu viewifi-host@TU_USUARIO   # ver el log en vivo
```

O instalación en una línea:

```bash
curl -sSL https://raw.githubusercontent.com/pipe9494/viewifi_linux/main/install.sh | sudo bash
```

Sin dependencias de Python: **todo funciona con la librería estándar** (hasta el PNG de la alerta se dibuja a mano con `zlib`). Las herramientas de evidencia (`fswebcam`, `arecord`, `ffmpeg`) son opcionales.

## Panel web (interfaz gráfica)

Al arrancar, el host sirve un **panel de control web** en el puerto 8080 — no necesitas tocar la terminal:

```
http://IP-DEL-HOST:8080     (por ejemplo http://192.168.1.50:8080)
```

Ábrelo desde cualquier PC, tablet o celular de tu red. Incluye:

- **Señal WiFi en vivo** con línea base, umbral y marcadores de perturbación
- Tarjetas de estado: RSSI, ruido σ, desviación, eventos del día
- Controles: **armar / desarmar / recalibrar** y prueba de Telegram
- **Toda la configuración** (Telegram, sensibilidad, horario protegido, evidencias, Supabase) — se guarda en caliente
- Historial de eventos recientes con nivel y clasificación
- Contraseña opcional (`web_password`) si no quieres el panel abierto en tu LAN

## Qué hace

| Función | Detalle |
|---|---|
| Detección por WiFi | `iw dev link` → `/proc/net/wireless` → `iwconfig` (fallbacks automáticos) |
| Alertas Telegram | Foto con la **onda RSSI renderizada** al momento de la alarma |
| Evidencia real | Foto de webcam (`fswebcam`/`ffmpeg`) + clip de audio (`arecord`), opcionales |
| Comandos remotos | `/status` `/arm` `/disarm` `/photo` `/help` desde tu chat de Telegram |
| Geofence | Comandos arm/disarm desde la app Android vía Supabase `device_commands` |
| Multi-host | Se registra en `host_registry`: aparece por nombre en el selector de la app |
| Alarma por caída de WiFi | Si desaparece la señal >10 s estando armado (router apagado/jamming) → HIGH |
| Horario protegido | Escala a HIGH dentro de la ventana; fuera de ella registra sin molestar |
| Digest diario | Resumen a medianoche con conteos por nivel |
| Routine watch | Compara cada hora de ayer contra el promedio de los últimos 7 días |
| Latidos | Heartbeat periódico a Telegram para saber que el host sigue vivo |
| 24/7 | systemd: `Restart=always`, arranque con el sistema, límite de 256 MB |

## Configuración

`python3 -m viewifi.main --setup` te guía paso a paso, o edita `~/.viewifi/config.json` (ver `config.example.json`).

- **Solo Telegram**: deja vacío el bloque Supabase → alertas y comandos locales funcionan igual.
- **Con Supabase**: usa la **misma cuenta** que en la app Android y ejecuta el SQL de `docs/supabase_schema.sql` (tablas `device_commands` y `host_registry`) en el dashboard de tu proyecto.

## Probar sin hardware

```bash
python3 -m viewifi.main --sim   # señal sintética con perturbaciones
python3 -m viewifi.engine       # self-test del motor: 7 escenarios
```

## Consejos de campo

- Deja el host **fijo** y quieto durante los 30 s de calibración.
- Casas "ruidosas" (ventiladores, aire acondicionado): sube `sensitivity` a 3.0–3.5.
- En la Pi, conecta por Ethernet si puedes: el RSSI se mide sobre el WiFi, así que el host debe usar WiFi para su propia conexión... o usa un dongle USB-WiFi dedicado (`--iface wlan1`).

---

## English quick notes

- **Easiest**: download the prebuilt executable from [Releases](https://github.com/pipe9494/viewifi_linux/releases) (`viewifi-host-linux-x86_64` for PCs, `viewifi-host-linux-arm64` for Raspberry Pi 64-bit), `chmod +x` and run it — no Python needed.
- From source: `git clone … && sudo ./install.sh`, configure with `python3 -m viewifi.main --setup`, run `sudo systemctl start viewifi-host@USER`.
- **Web dashboard**: once running, open `http://HOST-IP:8080` from any browser on your LAN — live signal chart, arm/disarm/recalibrate, full configuration, event history. Optional password via `web_password`.
- Pure Python standard library; Telegram alerts carry a rendered RSSI waveform; optional webcam photo + mic audio; remote commands `/status /arm /disarm /photo`; Supabase geofence + multi-host shared with the Android app; systemd service for 24/7 operation.
- Engine self-test: `python3 -m viewifi.engine`. Demo without WiFi: `./viewifi-host-linux-x86_64 --sim`.

## Licencia

MIT — mismo espíritu que la app.
