# Prompt para el agente de GitHub Copilot

Abre `github.com/pipe9494/viewifi_linux`, entra en **Copilot → Agents** (o
asigna un issue a Copilot) y pega el bloque de abajo tal cual.

---

Reemplaza por completo el archivo `.github/workflows/release.yml` de este
repositorio con el contenido exacto que incluyo al final de este mensaje, y
ábreme un pull request con el cambio.

## Contexto

Este repositorio contiene el host de Linux de Viewifi: una aplicación en
Python que usa únicamente la biblioteca estándar, cuyo punto de entrada es
`run.py`. De ella se compilan dos ejecutables con PyInstaller,
`viewifi-host-linux-x86_64` y `viewifi-host-linux-arm64`, que se publican
como adjuntos de una release para que la web `viewifi.tech` pueda enlazarlos.

El workflow actual tiene dos defectos que hacen que esos dos enlaces de
descarga devuelvan 404 hoy mismo. El contenido nuevo que te doy ya los
corrige. Necesito que lo apliques literalmente, sin reescribirlo.

## Los dos defectos que el archivo nuevo corrige

Te los explico para que entiendas por qué está escrito así y **no intentes
"mejorarlo" deshaciéndolos**:

1. **Publicaba en el repositorio equivocado.** El workflow actual usa
   `gh release create` con el `GITHUB_TOKEN` por defecto. Ese token solo
   tiene permisos sobre este repositorio, así que las releases acababan en
   `pipe9494/viewifi_linux`. Pero la web enlaza a
   `pipe9494/viewifi-releases`, que es otro repositorio, y además este va a
   pasar a ser privado. El archivo nuevo sube a `viewifi-releases` usando un
   secret llamado `RELEASES_TOKEN`.

2. **Compilaba contra una glibc demasiado nueva.** Compilaba sobre
   `ubuntu-latest`, que trae glibc 2.39. Un binario así falla con
   `GLIBC_2.38 not found` en Raspberry Pi OS bookworm y en Debian 12, que es
   justo donde tiene que correr. El archivo nuevo compila dentro de un
   contenedor `debian:bullseye` (glibc 2.31). Compilar contra una glibc
   antigua y ejecutar sobre las nuevas funciona; al revés no.

## Reglas

- Aplica el contenido **exactamente** como te lo doy. No cambies la imagen
  del contenedor, ni los runners, ni los nombres de los archivos generados,
  ni el repositorio de destino, ni el `--clobber`, ni los comentarios.
- No modifiques ningún otro archivo. En concreto, no toques el código de
  `viewifi/`, ni `run.py`, ni `install.sh`, ni `.github/workflows/test.yml`.
- No añadas dependencias al proyecto: el host tiene que seguir usando solo
  la biblioteca estándar de Python.
- No subas la versión ni crees tags.
- **No intentes crear el secret `RELEASES_TOKEN`.** Un agente no puede crear
  secrets; eso lo hago yo a mano. Limítate a mencionarlo en la descripción
  del pull request como paso pendiente por mi parte.
- Si el linter de Actions se queja de `ubuntu-24.04-arm`, ignóralo: ese
  runner existe y es el correcto.

## Descripción del pull request

Incluye en ella, además del resumen del cambio, estos dos pasos manuales
que quedan de mi lado:

1. Crear un Personal Access Token con permiso de escritura sobre
   `pipe9494/viewifi-releases` y guardarlo en este repositorio como secret
   `RELEASES_TOKEN`, en Settings → Secrets and variables → Actions.
2. Lanzar el workflow a mano desde la pestaña Actions (`workflow_dispatch`)
   con el tag `v1.0.0`, que es la release donde ya está publicada la imagen
   del kit y donde tienen que convivir todos los adjuntos.

## Contenido exacto de `.github/workflows/release.yml`

```yaml
name: release

# Compila el host de Linux para x86_64 y ARM64 y sube los dos ejecutables
# a una release del repositorio PÚBLICO de descargas.
#
# Por qué está escrito así:
#
#  1. Los ejecutables se compilan dentro de un contenedor debian:bullseye
#     (glibc 2.31). Un binario compilado sobre el Ubuntu del runner (glibc
#     2.39) falla con "GLIBC_2.38 not found" en Raspberry Pi OS bookworm y en
#     Debian 12, que es justo donde va a correr. Compilar contra la glibc más
#     antigua y ejecutar sobre las nuevas sí funciona; al revés no.
#
#  2. Publica en pipe9494/viewifi-releases, no en este repositorio. El sitio
#     enlaza a viewifi-releases y este repo va a ser privado: una release aquí
#     daría 404 a cualquiera que no haya iniciado sesión.
#
#  3. Usa `gh release upload --clobber` sobre un tag que ya existe, en vez de
#     `gh release create`. Todos los archivos (imagen del kit, ejecutables y
#     APK) tienen que vivir en la MISMA release, porque la web enlaza a
#     /releases/latest/download/... y "latest" es una sola release.

on:
  workflow_dispatch:
    inputs:
      tag:
        description: "Tag de la release destino en viewifi-releases"
        required: true
        default: "v1.0.0"
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-24.04
            arch: x86_64
          - os: ubuntu-24.04-arm
            arch: arm64
    runs-on: ${{ matrix.os }}
    container: debian:bullseye
    steps:
      - name: Preparar el contenedor
        run: |
          apt-get update
          apt-get install -y --no-install-recommends \
            python3 python3-pip python3-dev binutils curl ca-certificates git

      - uses: actions/checkout@v4

      - name: Compilar el ejecutable
        run: |
          python3 -m pip install --upgrade pip
          python3 -m pip install pyinstaller
          python3 -m PyInstaller --onefile --strip \
            --name viewifi-host-linux-${{ matrix.arch }} run.py

      - name: Comprobar que arranca (modo simulación)
        run: |
          chmod +x dist/viewifi-host-linux-${{ matrix.arch }}
          ./dist/viewifi-host-linux-${{ matrix.arch }} --help
          ./dist/viewifi-host-linux-${{ matrix.arch }} --sim &
          PID=$!
          sleep 10
          curl -sf --max-time 5 http://127.0.0.1:8080/api/status | grep -q device_name
          curl -sf --max-time 5 http://127.0.0.1:8080/ | grep -qi viewifi
          kill "$PID" || true

      - name: Registrar la glibc mínima requerida
        run: |
          echo "Compilado en: $(ldd --version | head -1)"
          objdump -T dist/viewifi-host-linux-${{ matrix.arch }} 2>/dev/null \
            | grep -oE 'GLIBC_[0-9.]+' | sort -Vu | tail -1 \
            || echo "sin símbolos versionados"

      - uses: actions/upload-artifact@v4
        with:
          name: bin-${{ matrix.arch }}
          path: dist/viewifi-host-linux-${{ matrix.arch }}
          if-no-files-found: error

  publish:
    needs: build
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: bin-*
          merge-multiple: true

      - name: Subir a la release de viewifi-releases
        env:
          # Token personal con permiso de escritura sobre viewifi-releases.
          # El GITHUB_TOKEN por defecto solo sirve para ESTE repositorio.
          GH_TOKEN: ${{ secrets.RELEASES_TOKEN }}
          TAG: ${{ github.event.inputs.tag || github.ref_name }}
        run: |
          if [ -z "$GH_TOKEN" ]; then
            echo "::error::Falta el secret RELEASES_TOKEN."
            echo "Créalo en Settings → Secrets and variables → Actions."
            exit 1
          fi
          chmod +x viewifi-host-linux-*
          ls -la viewifi-host-linux-*
          gh release upload "$TAG" viewifi-host-linux-* \
            --clobber --repo pipe9494/viewifi-releases
          echo "Subidos a la release $TAG de pipe9494/viewifi-releases."
```
