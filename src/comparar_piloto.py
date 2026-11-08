"""Compara la última extracción con el Excel piloto y muestra todas las diferencias.

Uso: python src/comparar_piloto.py [FECHA]

Empareja por clave_normalizada. No compara `observaciones` (escritas a mano en el
piloto), `descripcion` (vacía en el piloto) ni `fecha_captura`.
"""
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

RAIZ = Path(__file__).resolve().parent.parent
CAMPOS = ["tipo", "entidad_colaboradora", "director", "web", "email", "campus_centro", "url_origen"]
ESPERADO = {"UPV": 89, "UV": 65}


def piloto():
    hoja = load_workbook(RAIZ / "catedras_piloto_UPV_UV.xlsx", read_only=True, data_only=True)["Cátedras"]
    filas = list(hoja.iter_rows(values_only=True))
    return [dict(zip(filas[0], f)) for f in filas[1:]]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    base = RAIZ / "data" / "parsed"
    fecha = sys.argv[1] if len(sys.argv) > 1 else max(p.name for p in base.iterdir() if p.is_dir())
    print("Captura comparada:", fecha)
    excel = piloto()
    for sig, esperado in ESPERADO.items():
        nuevos = json.loads((base / fecha / f"{sig.lower()}.json").read_text(encoding="utf-8"))
        nuevos = [f for f in nuevos if f["tipo"] == "Cátedra"]  # el piloto no incluía aulas
        viejos = [f for f in excel if f["universidad"] == sig]
        n = {f["clave_normalizada"]: f for f in nuevos}
        v = {f["clave_normalizada"]: f for f in viejos}
        print(f"\n===== {sig}: {len(nuevos)} registros (esperados {esperado}; claves distintas {len(n)})")
        solo_n, solo_v = sorted(set(n) - set(v)), sorted(set(v) - set(n))
        print(f"Solo en la web de hoy: {len(solo_n)}")
        for k in solo_n:
            print("  +", k, "|", n[k]["nombre"])
        print(f"Solo en el Excel: {len(solo_v)}")
        for k in solo_v:
            print("  -", k, "|", v[k]["nombre"])
        for campo in CAMPOS:
            difs = [k for k in sorted(set(n) & set(v)) if (n[k][campo] or None) != (v[k][campo] or None)]
            print(f"Diferencias en {campo}: {len(difs)}")
            for k in difs:
                print(f"  {k}\n      web:   {n[k][campo]!r}\n      excel: {v[k][campo]!r}")
        comunes = set(n) & set(v)
        distintos = sum(n[k]["nombre"] != v[k]["nombre"] for k in comunes)
        print(f"Nombres escritos de otra forma (misma clave): {distintos}")
        for k in sorted(comunes):
            if n[k]["nombre"] != v[k]["nombre"]:
                print(f"  web: {n[k]['nombre']!r}  excel: {v[k]['nombre']!r}")
        con_desc = sum(1 for f in nuevos if f["descripcion"])
        print(f"Con descripción (no estaba en el piloto): {con_desc}")


if __name__ == "__main__":
    main()
