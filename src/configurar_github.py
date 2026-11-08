"""Deja lista la actualización en GitHub. Se ejecuta una vez, o al renovar el permiso. No usa IA.

Uso: python src/configurar_github.py

Pide en el terminal, sin mostrarlos, la contraseña de la página y el permiso creado en GitHub.
Comprueba ambos y guarda en GitHub, como secretos, la clave derivada de la contraseña (no la
contraseña) y el permiso. Después lanza una actualización, que publica el botón en la página.
"""
import base64
import getpass
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_web import derivar_clave, descifrar  # noqa: E402

REPO = "Googol-IA/catedras-universidades"
URL_DATOS = "https://googol-ia.github.io/catedras-universidades/datos.enc.json"


def gh(*orden, entrada=None):
    r = subprocess.run(["gh", *orden], input=entrada, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"Ha fallado «gh {orden[0]}»:\n{r.stderr.strip()}")
    return r.stdout


def leer_paquete():
    pedido = urllib.request.Request(URL_DATOS, headers={"User-Agent": "catedras-configurar", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(pedido, timeout=60) as r:
        return json.load(r)


def permiso_valido(token):
    pedido = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/workflows",
                                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "catedras-configurar"})
    try:
        with urllib.request.urlopen(pedido, timeout=30):
            return True
    except urllib.error.URLError:
        return False


def main():
    if not sys.stdin.isatty():
        sys.exit("Este programa necesita un terminal para pedir los datos sin que se vean.")
    print("Lo que escribas no se verá en pantalla. Es normal.\n")
    paquete = leer_paquete()
    sal = base64.b64decode(paquete["sal"])
    while True:
        clave = derivar_clave(getpass.getpass("Contraseña de la página: "), sal)
        try:
            descifrar(paquete, clave)
            print("Contraseña correcta.\n")
            break
        except Exception:
            print("No es la contraseña de la página. Vuelve a probar.")
    while True:
        token = getpass.getpass("Permiso de GitHub (pégalo y pulsa Enter): ").strip()
        if permiso_valido(token):
            print("Permiso correcto.\n")
            break
        print("GitHub no acepta ese permiso. Revisa que sea de este repositorio y vuelve a probar.")

    gh("secret", "set", "CLAVE_CIFRADO", "--repo", REPO, entrada=base64.b64encode(clave).decode())
    gh("secret", "set", "SAL_CIFRADO", "--repo", REPO, entrada=paquete["sal"])
    gh("secret", "set", "TOKEN_BOTON", "--repo", REPO, entrada=token)
    print("Secretos guardados en GitHub.")
    gh("workflow", "run", "actualizar.yml", "--repo", REPO)
    print("Actualización lanzada. Cuando termine, la página tendrá el botón «Actualizar datos».")


if __name__ == "__main__":
    main()
