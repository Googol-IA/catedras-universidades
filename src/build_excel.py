"""Reúne la captura más reciente y genera el Excel final (Fase 4). No usa IA.

Uso: python src/build_excel.py

Lee data/parsed/FECHA/ y data/qa/FECHA/, y escribe
output/catedras_universidades_FECHA.xlsx con las hojas Cátedras, Universidades,
Errores y Cambios. `cargar_todo` también la usa build_web.py.
"""
import csv
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import COLUMNAS  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ANCHOS = {"universidad": 11, "nombre": 58, "tipo": 9, "entidad_colaboradora": 34, "director": 30, "web": 38, "email": 28,
          "campus_centro": 28, "url_origen": 38, "fecha_captura": 12, "clave_normalizada": 38, "observaciones": 40, "descripcion": 60}
CAMPOS_UNIVERSIDADES = ["universidad", "nombre_completo", "comunidad", "estado", "n_registros", "listado_central", "url_catedras",
                        "carga_con_javascript", "metodo_descarga", "ultima_captura", "notas"]
CAMPOS_ERRORES = ["universidad", "tipo", "detalle"]
CAMPOS_CAMBIOS = ["fecha", "universidad", "nombre", "tipo_cambio", "campo", "valor_anterior", "valor_nuevo"]


def leer_csv(ruta):
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def cargar_todo(fecha=None):
    """Devuelve fecha, filas de cátedras (con observaciones), universidades y errores."""
    base = RAIZ / "data" / "parsed"
    fecha = fecha or max(p.name for p in base.iterdir() if p.is_dir())
    universidades = leer_csv(RAIZ / "universidades.csv")
    errores = leer_csv(RAIZ / "data" / "qa" / fecha / "errores.csv")
    motivos = {}
    for c in leer_csv(RAIZ / "data" / "qa" / fecha / "compartidas.csv"):
        motivos.setdefault(c["clave_normalizada"], []).append(c["motivo"])

    filas = []
    for u in universidades:
        ruta = base / fecha / f"{u['universidad'].lower()}.json"
        if not ruta.exists():
            continue
        for f in json.loads(ruta.read_text(encoding="utf-8")):
            notas = f["observaciones"].split(" · ") if f["observaciones"] else []
            notas += [m for m in motivos.get(f["clave_normalizada"], []) if m not in notas]
            f["observaciones"] = " · ".join(notas) or None
            filas.append(f)
    return fecha, filas, universidades, errores


def leer_cambios(fecha):
    ruta = RAIZ / "data" / "parsed" / fecha / "_cambios.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


def escribir_hoja(hoja, campos, filas, nombre_tabla, anchos=None):
    hoja.append(campos)
    for f in filas:
        hoja.append([f.get(c) for c in campos])
    for i, campo in enumerate(campos, start=1):
        letra = get_column_letter(i)
        hoja.column_dimensions[letra].width = (anchos or {}).get(campo, 22)
    hoja.freeze_panes = "A2"
    for c in hoja[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(vertical="center")
    if filas:  # una tabla de Excel trae filtros y orden en cada columna
        tabla = Table(displayName=nombre_tabla, ref=f"A1:{get_column_letter(len(campos))}{len(filas) + 1}")
        tabla.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
        hoja.add_table(tabla)
    else:
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(campos))}1"


def construir(ruta_salida=None):
    fecha, filas, universidades, errores = cargar_todo()
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Cátedras"
    escribir_hoja(hoja, COLUMNAS, filas, "Catedras", ANCHOS)
    col_web = COLUMNAS.index("web") + 1
    for fila in range(2, len(filas) + 2):
        celda = hoja.cell(row=fila, column=col_web)
        if celda.value:
            celda.hyperlink = celda.value
            celda.font = Font(color="1F4E9E", underline="single")
    escribir_hoja(libro.create_sheet("Universidades"), CAMPOS_UNIVERSIDADES, universidades, "Universidades",
                  {"nombre_completo": 44, "url_catedras": 50, "notas": 70, "universidad": 11, "estado": 13, "n_registros": 11})
    hoja_errores = libro.create_sheet("Errores")
    escribir_hoja(hoja_errores, CAMPOS_ERRORES, errores, "Errores", {"universidad": 11, "tipo": 12, "detalle": 110})
    escribir_hoja(libro.create_sheet("Cambios"), CAMPOS_CAMBIOS, leer_cambios(fecha), "Cambios",
                  {"fecha": 12, "universidad": 11, "nombre": 58, "tipo_cambio": 24, "campo": 20, "valor_anterior": 40, "valor_nuevo": 40})
    salida = ruta_salida or RAIZ / "output" / f"catedras_universidades_{fecha}.xlsx"
    salida.parent.mkdir(parents=True, exist_ok=True)
    libro.save(salida)
    return salida, fecha, filas, universidades, errores


if __name__ == "__main__":
    salida, fecha, filas, universidades, errores = construir()
    print(f"{salida.name}: {len(filas)} registros, {len(universidades)} universidades, {len(errores)} avisos ({salida.stat().st_size // 1024} KB)")
