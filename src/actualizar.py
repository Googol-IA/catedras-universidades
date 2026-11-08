"""Proceso completo de actualización. Es lo que ejecuta GitHub. No usa IA.

Uso:
    python src/actualizar.py                descarga, compara, valida y publica cifrado
    python src/actualizar.py --solo-probar  solo descarga y extrae, para ver qué webs responden

Necesita estas variables (secretos de GitHub), salvo con --solo-probar:
    CLAVE_CIFRADO, SAL_CIFRADO   clave derivada de la contraseña; la contraseña no se guarda
    TOKEN_BOTON                  permiso limitado para el botón; viaja dentro de lo cifrado
"""
import base64
import csv
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_web  # noqa: E402
import extract  # noqa: E402
from diff import comparar  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
REPO = os.environ.get("GITHUB_REPOSITORY", "Googol-IA/catedras-universidades")
HISTORIAL_MAXIMO = 5000


def inventario():
    with open(RAIZ / "universidades.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def descargar():
    # Un fallo en una web no detiene el proceso: fetch lo anota y aquí se detecta al extraer.
    subprocess.run([sys.executable, str(RAIZ / "src" / "fetch.py")], check=False)


def solo_probar(fecha):
    filas, fallos = extract.extraer_todas(fecha)
    previos = {u["universidad"]: u.get("n_registros", "") for u in inventario()}
    print("\nRESULTADO DE LA PRUEBA")
    print(f"{'Universidad':10}{'Ahora':>7}{'Antes':>7}  Situación")
    for sig in extract.EXTRACTORES:
        n, antes = len(filas.get(sig, [])), previos.get(sig, "")
        situacion = f"FALLO: {fallos[sig]}" if sig in fallos else ("sin registros" if not n else ("distinto" if str(n) != str(antes) else "igual"))
        print(f"{sig:10}{n:7}{antes:>7}  {situacion}")
    print(f"\nCon datos: {sum(1 for v in filas.values() if v)} de {len(extract.EXTRACTORES)}. Con fallo: {len(fallos)}.")


def main():
    fecha = datetime.date.today().isoformat()
    descargar()
    if "--solo-probar" in sys.argv:
        solo_probar(fecha)
        return

    clave, sal = base64.b64decode(os.environ["CLAVE_CIFRADO"]), base64.b64decode(os.environ["SAL_CIFRADO"])
    previo = build_web.descifrar(json.loads((RAIZ / "datos.enc.json").read_text(encoding="utf-8")), clave)

    nuevas, fallos = extract.extraer_todas(fecha)
    siglas = [u["universidad"] for u in inventario()]
    finales, cambios, pendientes, avisos = comparar(previo["catedras"], previo["fecha"], nuevas, fallos, fecha, previo.get("pendientes", {}), siglas)

    carpeta = RAIZ / "data" / "parsed" / fecha
    carpeta.mkdir(parents=True, exist_ok=True)
    for sig in siglas:
        ruta = carpeta / f"{sig.lower()}.json"
        if sig in finales:
            ruta.write_text(json.dumps(finales[sig], ensure_ascii=False), encoding="utf-8")
        elif ruta.exists():
            ruta.unlink()
    historial = (previo.get("cambios", []) + cambios)[-HISTORIAL_MAXIMO:]
    (carpeta / "_cambios.json").write_text(json.dumps(historial, ensure_ascii=False), encoding="utf-8")
    (carpeta / "_avisos.json").write_text(json.dumps(avisos, ensure_ascii=False), encoding="utf-8")

    subprocess.run([sys.executable, str(RAIZ / "src" / "validate.py")], check=True)
    token = os.environ.get("TOKEN_BOTON")
    n, _ = build_web.construir_web(RAIZ, clave=clave, sal=sal, pendientes=pendientes,
                                   github={"repo": REPO, "token": token} if token else None)
    print(f"Actualizado: {n} registros, {len(cambios)} cambios nuevos, {len(avisos)} universidades con problemas.")
    for a in avisos:
        print(f"  {a['universidad']}: {a['detalle']}")


if __name__ == "__main__":
    main()
