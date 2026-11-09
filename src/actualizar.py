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
import emails  # noqa: E402
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


def incorporar_busqueda(previo, clave):
    """Si hay una búsqueda a fondo recién subida (cifrada), la añade a los datos anteriores.

    Se hace antes de comparar para que no aparezcan como cientos de «Modificación» en Cambios.
    """
    ruta = RAIZ / "emails.enc.json"
    if not ruta.exists():
        return
    busqueda = build_web.descifrar(json.loads(ruta.read_text(encoding="utf-8")), clave)
    for f in previo["catedras"]:
        if f.get("email") and not f.get("email_tipo"):
            f["email_tipo"] = emails.TIPO_LISTADO
        asignado = busqueda["asignados"].get(f["clave_normalizada"])
        if asignado and not f.get("email"):
            f.update(asignado)
    previo["emails_desde"] = busqueda["fecha"]
    previo["emails_genericos"] = busqueda["genericos"]
    ruta.unlink()
    print(f"Búsqueda de emails del {busqueda['fecha']} incorporada: {len(busqueda['asignados'])} cátedras.")


def incorporar_manuales(previo, clave):
    """Si hay una lista de cátedras localizadas a mano recién subida (cifrada), la guarda en los datos.

    Se añaden también a los datos anteriores para que no cuenten como altas en Cambios.
    """
    ruta = RAIZ / "manuales.enc.json"
    if not ruta.exists():
        return
    manuales = build_web.descifrar(json.loads(ruta.read_text(encoding="utf-8")), clave)["filas"]
    claves = {f["clave_normalizada"] for f in manuales}
    previo["catedras"] = [f for f in previo["catedras"] if f["clave_normalizada"] not in claves] + manuales
    previo["manuales"] = manuales
    ruta.unlink()
    print(f"Cátedras localizadas a mano incorporadas: {len(manuales)}.")


def añadir_manuales(nuevas, manuales):
    """Las localizadas a mano siguen en la lista: el programa no las revisa porque no salen de un listado."""
    for f in manuales:
        lista = nuevas.setdefault(f["universidad"], [])
        if f["clave_normalizada"] not in {x["clave_normalizada"] for x in lista}:
            lista.append(dict(f))


def main():
    fecha = datetime.date.today().isoformat()
    descargar()
    if "--solo-probar" in sys.argv:
        solo_probar(fecha)
        return

    clave, sal = base64.b64decode(os.environ["CLAVE_CIFRADO"]), base64.b64decode(os.environ["SAL_CIFRADO"])
    previo = build_web.descifrar(json.loads((RAIZ / "datos.enc.json").read_text(encoding="utf-8")), clave)

    incorporar_busqueda(previo, clave)
    incorporar_manuales(previo, clave)
    nuevas, fallos = extract.extraer_todas(fecha)
    añadir_manuales(nuevas, previo.get("manuales", []))
    genericos = previo.get("emails_genericos", {})
    buscadas, halladas = emails.aplicar(nuevas, previo["catedras"], genericos)
    print(f"Emails: {buscadas} cátedras nuevas buscadas, {halladas} con email.")
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
                                   github={"repo": REPO, "token": token} if token else None,
                                   extra={"emails_desde": previo.get("emails_desde"), "emails_genericos": genericos, "manuales": previo.get("manuales", [])})
    print(f"Actualizado: {n} registros, {len(cambios)} cambios nuevos, {len(avisos)} universidades con problemas.")
    for a in avisos:
        print(f"  {a['universidad']}: {a['detalle']}")


if __name__ == "__main__":
    main()
