"""Genera la página web con los datos cifrados (Fase 4). No usa IA.

Uso:
    python src/build_web.py --salida CARPETA        pide la contraseña en el terminal

Escribe en CARPETA:
    index.html       la página (sin datos)
    datos.enc.json   los datos y el Excel cifrados: JSON → gzip → AES-256-GCM
                     con clave PBKDF2-SHA256 de 600.000 iteraciones y sal aleatoria

La contraseña no se guarda en ningún sitio.
"""
import argparse
import base64
import getpass
import gzip
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_excel import construir, leer_cambios  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = Path(__file__).resolve().parent / "web" / "index.html"
ITERACIONES = 600_000
MINIMO_CONTRASENA = 12
CAMPOS_FILA = ["fecha_captura", "universidad", "nombre", "tipo", "entidad_colaboradora", "director", "web", "email", "campus_centro",
               "url_origen", "clave_normalizada", "observaciones", "descripcion"]
CAMPOS_UNIVERSIDAD = ["universidad", "nombre_completo", "comunidad", "estado", "n_registros", "url_catedras"]


def b64(datos):
    return base64.b64encode(datos).decode("ascii")


def derivar_clave(contrasena, sal):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACIONES).derive(contrasena.encode("utf-8"))


def descifrar(paquete, clave):
    plano = AESGCM(clave).decrypt(base64.b64decode(paquete["iv"]), base64.b64decode(paquete["datos"]), None)
    return json.loads(gzip.decompress(plano))


def cifrar(contenido, clave, sal):
    iv = os.urandom(12)
    comprimido = gzip.compress(json.dumps(contenido, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)
    return {"sal": b64(sal), "iv": b64(iv), "iteraciones": ITERACIONES, "datos": b64(AESGCM(clave).encrypt(iv, comprimido, None))}


def construir_web(carpeta, contrasena=None, clave=None, sal=None, pendientes=None, github=None):
    """Con contraseña crea clave y sal nuevas; en las actualizaciones se reutiliza la clave guardada."""
    if clave is None:
        sal = os.urandom(16)
        clave = derivar_clave(contrasena, sal)
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:  # el Excel solo viaja dentro del paquete cifrado
        ruta_excel, fecha, filas, universidades, errores = construir(Path(tmp) / "catedras.xlsx")
        excel = b64(ruta_excel.read_bytes())
    contenido = {
        "fecha": fecha,
        "catedras": [{c: f[c] for c in CAMPOS_FILA if f.get(c)} for f in filas],
        "universidades": [{c: u.get(c, "") for c in CAMPOS_UNIVERSIDAD} for u in universidades],
        "errores": errores,
        "excel": excel,
        "cambios": leer_cambios(fecha),
        "pendientes": pendientes or {},
    }
    if github:
        contenido["github"] = github
    paquete = cifrar(contenido, clave, sal)
    version = f"{fecha}-{paquete['iv'][:8]}".replace("/", "_").replace("+", "-")
    paquete["version"] = version
    (carpeta / "datos.enc.json").write_text(json.dumps(paquete), encoding="utf-8")
    (carpeta / "index.html").write_text(PLANTILLA.read_text(encoding="utf-8").replace("__VERSION__", version), encoding="utf-8")
    (carpeta / ".nojekyll").write_text("", encoding="utf-8")
    return len(filas), fecha


def pedir_contrasena():
    while True:
        a = getpass.getpass(f"Contraseña para la página (mínimo {MINIMO_CONTRASENA} caracteres; no se verá al escribir): ")
        if len(a) < MINIMO_CONTRASENA:
            print("Demasiado corta. Mejor 4 o 5 palabras sueltas.")
            continue
        if a != getpass.getpass("Repítela: "):
            print("No coinciden. Vuelve a probar.")
            continue
        return a


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--salida", required=True)
    parser.add_argument("--archivo-contrasena", help="Solo para pruebas: archivo con una contraseña de prueba")
    args = parser.parse_args()
    if args.archivo_contrasena:
        contrasena = Path(args.archivo_contrasena).read_text(encoding="utf-8").strip()
    else:
        contrasena = pedir_contrasena()
    n, fecha = construir_web(args.salida, contrasena)
    print(f"Página generada en {args.salida}: {n} registros, datos del {fecha}")


if __name__ == "__main__":
    main()
