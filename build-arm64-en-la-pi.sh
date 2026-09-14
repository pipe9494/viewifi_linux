#!/usr/bin/env bash
#
# Compila viewifi-host-linux-arm64 en la propia Raspberry Pi.
#
# Alternativa sin GitHub Actions: si prefieres no configurar el workflow,
# copia este script y la carpeta del código a una Pi y ejecútalo. Compilar
# en la propia Pi garantiza que el binario corre en esa familia de sistemas,
# porque se enlaza contra la glibc que ya tiene instalada.
#
#   scp -r viewifi_linux build-arm64-en-la-pi.sh pi@raspberrypi.local:~/
#   ssh pi@raspberrypi.local
#   cd ~ && bash build-arm64-en-la-pi.sh viewifi_linux
#
# Tarda entre 3 y 8 minutos según el modelo de Pi.

set -euo pipefail

SRC="${1:-.}"
OUT="viewifi-host-linux-arm64"

die() { printf '\n[error] %s\n' "$1" >&2; exit 1; }
info() { printf '\n== %s\n' "$1"; }

[[ -f "$SRC/run.py" ]] || die "No encuentro run.py dentro de '$SRC'. Pasa la ruta del código como primer argumento."

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
  die "Esta máquina es $ARCH, no ARM64. PyInstaller no compila para otra arquitectura: ejecuta esto en la Raspberry Pi (con Raspberry Pi OS de 64 bits) o usa el workflow de GitHub Actions."
fi

info "Instalando lo necesario"
sudo apt-get update
sudo apt-get install -y --no-install-recommends python3 python3-pip python3-dev binutils curl

info "Instalando PyInstaller"
# --break-system-packages hace falta desde Debian 12; en Debian 11 no existe
# esa opción, así que se intenta primero y se cae al modo clásico.
python3 -m pip install --upgrade pyinstaller --break-system-packages 2>/dev/null \
  || python3 -m pip install --upgrade pyinstaller

info "Compilando"
cd "$SRC"
rm -rf build dist
python3 -m PyInstaller --onefile --strip --name "$OUT" run.py

[[ -f "dist/$OUT" ]] || die "PyInstaller terminó pero no generó dist/$OUT."
chmod +x "dist/$OUT"

info "Comprobando que arranca"
"./dist/$OUT" --help >/dev/null || die "El ejecutable no responde a --help."

"./dist/$OUT" --sim >/tmp/viewifi-build-test.log 2>&1 &
PID=$!
sleep 10
if curl -sf --max-time 5 http://127.0.0.1:8080/api/status | grep -q device_name; then
  echo "   El panel responde correctamente."
else
  kill "$PID" 2>/dev/null || true
  die "El panel no respondió en el puerto 8080. Revisa /tmp/viewifi-build-test.log"
fi
kill "$PID" 2>/dev/null || true

GLIBC="$(ldd --version | head -1)"
SIZE="$(du -h "dist/$OUT" | cut -f1)"

cat <<FIN

======================================================================
 Listo: $(pwd)/dist/$OUT  ($SIZE)

 Compilado contra: $GLIBC
 Correrá en esta versión de Raspberry Pi OS y en las posteriores.
 Si lo compilas en Bookworm, no funcionará en Bullseye.

 Para subirlo a la release (desde un equipo con el gh CLI autenticado):

   gh release upload v1.0.0 dist/$OUT \\
     --clobber --repo pipe9494/viewifi-releases

 Tiene que ir a la MISMA release v1.0.0 que la imagen del kit: la web
 enlaza a /releases/latest/download/... y "latest" es una sola release.
======================================================================

FIN
