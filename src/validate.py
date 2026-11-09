"""Control de calidad de una captura (Fase 3). No usa IA.

Uso:
    python src/validate.py                 comprobaciones sobre lo ya descargado
    python src/validate.py --enlaces       además abre los enlaces de la muestra

Escribe en data/qa/FECHA/:
    recuento.csv        registros por universidad frente a cifras que ella publica
    no_capturadas.csv   textos tipo «Cátedra X» de sus páginas que no están en los datos
    datos_sospechosos.csv  datos extraídos que no aparecen en la página de origen
    casi_repetidas.csv  nombres muy parecidos dentro de una universidad
    compartidas.csv     posibles cátedras compartidas entre universidades
    muestra.csv         10 filas al azar por universidad, siempre las mismas
    errores.csv         avisos por universidad (la hoja «Errores» del Excel)

Además actualiza n_registros, ultima_captura y estado en universidades.csv.
"""
import csv
import difflib
import glob
import json
import random
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun import clave_normalizada  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TAM_MUESTRA = 10

# Cifras que la propia universidad publica. Referencia para contrastar, no verdad absoluta.
CIFRAS_PUBLICADAS = {
    "UCA": (18, "Noticia UCA sept. 2025: 17 activas y 1 en constitución"),
    "UJI": (43, "Web de cifras de la UJI, curso 2023/2024: cátedras y aulas"),
    "UAM": (31, "Noticia UAM reciente: 31 vigentes (35 en mayo de 2025)"),
    "UPM": (75, "Noticia UPM sin fecha clara"),
    "UNIOVI": (52, "Su página: 46 + 6 convenios activos"),
    "UNIZAR": (110, "Su portal indica 110; datos básicos 2025: 108"),
    "UB": (71, "Su buscador: 71 resultados"),
    "UDL": (21, "Portada de la UdL: 21 cátedras universidad-empresa"),
    "UPC": (19, "Memoria UPC: 19 cátedras de empresa"),
    "UDC": (28, "Nota UDC 2022: 25 cátedras y 3 aulas"),
    "UNED": (19, "Presentación OTC 2023: 19 en vigor"),
    "US": (42, "Memoria 2022-2023: 42 cátedras de empresa"),
    "USC": (None, ""),
}

# Resultado de la revisión manual de la Fase 3 (2026-11-08). Cada aviso explica qué falta por aclarar.
AVISOS = {
    "UCA": "Lista posiblemente incompleta: la web muestra 13 («Actualizada 09/05/2025»), una noticia de la UCA de 2025 cita 17 activas y 1 en constitución.",
    "UAB": "Lista posiblemente incompleta: solo muestra 9 cátedras, sin más datos.",
    "UJI": "Da 36 (25 cátedras y 11 aulas) frente a 43 de su web de cifras 2023/2024.",
    "UAM": "Da 39 cátedras y 6 aulas; una noticia de la UAM cita 31 cátedras vigentes: puede incluir no vigentes.",
    "UPM": "6 cátedras terminadas según sus fechas, conservadas y avisadas en observaciones.",
    "UCM": "PDF con fecha 9 de junio de 2025: puede estar desactualizado. Algunas figuran en trámite de renovación.",
    "UNEX": "Datos abiertos que podrían estar desactualizados: la web de Transferencia no da una lista para contrastar.",
    "UGR": "Tres listados que no coinciden: se unen dos; el de Secretaría General (junio de 2022) no se usa.",
    "UCO": "Une tres listados; algunas cátedras tienen nombres muy distintos y podrían quedar duplicadas. Incluye 28 aulas de proyección social y cultural; no se han buscado aulas culturales parecidas en otras universidades.",
    "UHU": "Noticias o búsquedas mencionan Fundación Moeve y AMINER, que no aparecen en su listado.",
    "UPC": "Da 24 frente a 19 de una memoria de la UPC sin fecha clara.",
    "ULL": "El enlace a «Aulas y cátedras culturales» de su portada da error 404: no incluidas.",
    "ULE": "Una cátedra figura como no activa en la web: conservada y avisada.",
    "ULPGC": "Solo la sección de vigentes más reciente (2026); las de 2024 y 2025 que no siguen en ella no se incluyen.",
    "UMH": "Sus páginas de cátedras institucionales y de investigación necesitan navegador; algún enlace de cátedras de empresa da 404.",
}
ENLACES_ROTOS = {
    "UCA": "Enlaces que no abrían en la revisión: Tecnalia, Dolor (Grünenthal), Veterinaria.",
    "UNIA": "Enlace que no abría en la revisión: Inteligencia Institucional.",
    "US": "Enlaces que no abrían en la revisión: Extenda, Endesa Red.",
    "UNICAN": "Enlace que no abría en la revisión: ENSA.",
    "UVA": "Enlace que no abría en la revisión: Estudios Hispánicos.",
    "UNEX": "De 10 enlaces revisados, 4 no abrían.",
}
ESTADOS_SIN_LISTADO = {"USAL": "Sin listado central: noticias y Vicerrectorado de Transferencia.", "UIMP": "Sin listado central: solo noticias sueltas."}
# Privadas sin listado: se muestra su nota del inventario, que indica dónde mirar. No se ha buscado cátedra por cátedra.
AVISOS.update({
    "UEM": "Sin listado: tres páginas sueltas de la web común a las cuatro universidades Europea; no consta a cuál pertenece cada cátedra.",
    "CUNEF": "Sin listado: solo se ha localizado la página de esta cátedra. Puede tener más.",
    "IE": "Sin listado: solo se ha localizado la página de esta cátedra, sin que conste el campus. Puede tener más.",
    "UNEATLANTICO": "Sin listado: solo se ha localizado la página de esta cátedra. Puede tener más.",
    "URL": "Solo las de la propia universidad; cada centro puede tener las suyas.",
    "NEBRIJA": "Su listado incluye además observatorios, que no se recogen.",
    "COMILLAS": "Su listado incluye además observatorios, que no se recogen.",
})

DETECTOR = re.compile(r"(?:C[ÁA]TEDRA|Cátedra|Càtedra|Catedra|Aula|AULA)\s+[^\s<>|]+(?:[ \t]+[^\s<>|.,;:]+){0,7}")
GENERICAS = re.compile(
    r"^(?:c[àáa]tedra|aula)s?\s+(?:de\s+(?:la\s+)?|del\s+|en\s+|y\s+|i\s+|universitari[ao]s?\b|institucional(?:es)?\b|"
    r"externas?\b|extraordinarias?\b|virtual\b|global\b|digital\b|ulpgc\b|uma\b|es\b|se\b|tiene\b|cuenta\b|nace\b|surge\b|"
    r"será\b|sera\b|ha\b|fue\b|para\b|por\b|con\b|que\b|a\b|el\b|la\b|las\b|los\b|un\b|una\b|d'|dels?\b)",
    re.I)


def sin_tildes(t):
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def plano(t):
    return re.sub(r"[^a-z0-9@./:-]+", " ", sin_tildes(t)).strip()


def texto_visible(ruta):
    sopa = BeautifulSoup(ruta.read_bytes(), "html.parser")
    for e in sopa(["script", "style", "noscript", "nav", "header", "footer"]):
        e.decompose()
    return sopa.get_text("\n"), {a.get("href", "") for a in sopa.find_all("a")}


def guardar(ruta, filas, campos):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fecha = max(p.name for p in (RAIZ / "data" / "parsed").iterdir() if p.is_dir())
    bruto, datos = RAIZ / "data" / "raw" / fecha, RAIZ / "data" / "parsed" / fecha
    salida = RAIZ / "data" / "qa" / fecha
    salida.mkdir(parents=True, exist_ok=True)
    with open(RAIZ / "universidades.csv", encoding="utf-8-sig", newline="") as f:
        inventario = list(csv.DictReader(f, delimiter=";"))

    todas, recuento, faltan, sospechosos, casi = {}, [], [], [], []
    for u in inventario:
        sig = u["universidad"]
        ruta = datos / f"{sig.lower()}.json"
        if not ruta.exists():
            recuento.append({"universidad": sig, "registros": 0, "listado_central": u["listado_central"], "cifra_publicada": "", "fuente_cifra": ""})
            continue
        filas = json.loads(ruta.read_text(encoding="utf-8"))
        todas[sig] = filas
        cifra, fuente = CIFRAS_PUBLICADAS.get(sig, (None, ""))
        recuento.append({"universidad": sig, "registros": len(filas), "cifras_catedras": sum(f["tipo"] == "Cátedra" for f in filas),
                         "aulas": sum(f["tipo"] == "Aula" for f in filas), "listado_central": u["listado_central"],
                         "cifra_publicada": cifra or "", "diferencia": len(filas) - cifra if cifra else "", "fuente_cifra": fuente})

        # 1. Textos «Cátedra X» en sus páginas que no están entre los datos.
        conjuntos = [set(f["clave_normalizada"].split("|", 1)[1].split()) for f in filas]
        vistos = set()
        paginas = [p for p in sorted(bruto.glob(f"{sig.lower()}*.html")) if re.fullmatch(rf"{sig.lower()}(_(p)?\d+)?", p.stem)]
        visible_total, enlaces_total = "", set()
        for pag in paginas:
            visible, hrefs = texto_visible(pag)
            visible_total += "\n" + visible
            enlaces_total |= hrefs
            for m in DETECTOR.finditer(visible):
                cand = " ".join(m.group(0).split())
                if GENERICAS.match(cand) and not re.search(r"[A-ZÀ-Ú]{3,}", cand[7:]):
                    continue
                cl = set(clave_normalizada(sig, cand).split("|", 1)[1].split())
                if len(cl) < 1 or any(cl <= c for c in conjuntos):
                    continue
                # coincide con alguna cátedra por sus primeras palabras significativas
                if any(len(cl & c) >= max(2, len(cl) - 1) for c in conjuntos):
                    continue
                if cand.lower() not in vistos:
                    vistos.add(cand.lower())
                    faltan.append({"universidad": sig, "texto": cand, "pagina": pag.name})

        # 2. Cada dato debe aparecer en la página de origen (PDF y JSON van aparte).
        if paginas and sig not in ("UCM", "UNEX"):
            base = plano(visible_total)
            todo_html = plano(" ".join(p.read_bytes().decode("utf-8", "replace") for p in paginas))
            for f in filas:
                for campo in ("nombre", "director", "entidad_colaboradora", "campus_centro"):
                    if f[campo] and plano(f[campo])[:60] not in base and plano(f[campo])[:60] not in todo_html:
                        sospechosos.append({"universidad": sig, "nombre": f["nombre"], "campo": campo, "valor": f[campo][:150]})

        # 3. Nombres casi iguales dentro de la universidad.
        claves = sorted(f["clave_normalizada"].split("|", 1)[1] for f in filas)
        for i, a in enumerate(claves):
            for b in claves[i + 1:]:
                if difflib.SequenceMatcher(None, a, b).quick_ratio() > 0.9 and difflib.SequenceMatcher(None, a, b).ratio() > 0.9:
                    casi.append({"universidad": sig, "clave_a": a, "clave_b": b})

    # 4. Posibles compartidas entre universidades.
    compartidas = []
    nombres_universidad = {u["universidad"]: sin_tildes(u["nombre_completo"]) for u in inventario}
    genericos_uni = {s.lower() for s in nombres_universidad} | {"universidad", "universitat", "universidade", "universitaria", "universitaria", "uni"}
    por_nombre = {}
    for sig, filas in todas.items():
        for f in filas:
            clave = " ".join(p for p in f["clave_normalizada"].split("|", 1)[1].split() if p not in genericos_uni)
            por_nombre.setdefault(clave, []).append(f)
            nombre = sin_tildes(f["nombre"])
            motivos = []
            if re.search(r"inter-?unive", nombre):
                motivos.append("Interuniversitaria según su nombre")
            original = " ".join(filter(None, [f["nombre"], f["entidad_colaboradora"]]))
            if sig == "EHU":  # «UPV/EHU» es su propio nombre, no la UPV de Valencia
                original = original.replace("UPV/EHU", "")
            texto_buscar = sin_tildes(original)
            for otra, completo in nombres_universidad.items():
                corto = completo.split(" / ")[0]
                # Las siglas deben coincidir en mayúsculas: «Ús» en catalán no es la US.
                if otra != sig and (corto in texto_buscar or re.search(rf"(?<![\w/-]){otra}(?![\w/-])", original)):
                    motivos.append(f"Menciona a {otra}")
            if motivos:
                compartidas.append({"universidad": sig, "nombre": f["nombre"], "clave_normalizada": f["clave_normalizada"], "motivo": "; ".join(motivos)})
    for clave, grupo in por_nombre.items():
        unis = sorted({f["universidad"] for f in grupo})
        if len(unis) > 1 and clave:
            for f in grupo:
                compartidas.append({"universidad": f["universidad"], "nombre": f["nombre"], "clave_normalizada": f["clave_normalizada"],
                                    "motivo": "Mismo nombre en " + ", ".join(u for u in unis if u != f["universidad"]) + ": pueden ser cátedras distintas"})

    # 5. Muestra fija de 10 filas por universidad.
    azar = random.Random(20261108)
    muestra = []
    for sig, filas in todas.items():
        for f in azar.sample(filas, min(TAM_MUESTRA, len(filas))):
            muestra.append(dict(f))
    if "--enlaces" in sys.argv:
        sesion = requests.Session()
        sesion.headers["User-Agent"] = UA
        for f in muestra:
            f["estado_web"] = ""
            if f["web"]:
                try:
                    r = sesion.get(f["web"], timeout=20, stream=True)
                    f["estado_web"] = r.status_code
                    r.close()
                except requests.RequestException as e:
                    f["estado_web"] = type(e).__name__
                if f["estado_web"] != 200:  # segundo intento, más despacio y con otro método
                    time.sleep(3)
                    c = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", UA, "-o", "/dev/null", "-w", "%{http_code}", f["web"]],
                                       capture_output=True, text=True)
                    f["estado_web"] = int(c.stdout) if c.stdout.strip().isdigit() and int(c.stdout) else f["estado_web"]
                time.sleep(1)
    elif (salida / "muestra.csv").exists():  # sin --enlaces se conserva la última comprobación
        with open(salida / "muestra.csv", encoding="utf-8-sig", newline="") as f:
            previos = {r["web"]: r["estado_web"] for r in csv.DictReader(f, delimiter=";")}
        for f in muestra:
            f["estado_web"] = previos.get(f["web"], "") if f["web"] else ""

    guardar(salida / "recuento.csv", recuento, ["universidad", "registros", "cifras_catedras", "aulas", "listado_central", "cifra_publicada", "diferencia", "fuente_cifra"])
    guardar(salida / "no_capturadas.csv", faltan, ["universidad", "texto", "pagina"])
    guardar(salida / "datos_sospechosos.csv", sospechosos, ["universidad", "nombre", "campo", "valor"])
    guardar(salida / "casi_repetidas.csv", casi, ["universidad", "clave_a", "clave_b"])
    guardar(salida / "compartidas.csv", compartidas, ["universidad", "nombre", "clave_normalizada", "motivo"])
    guardar(salida / "muestra.csv", muestra, ["universidad", "nombre", "tipo", "director", "entidad_colaboradora", "web", "estado_web", "campus_centro", "email"])
    errores = []
    ruta_avisos = datos / "_avisos.json"
    con_error = {}
    if ruta_avisos.exists():  # problemas de esta actualización (los escribe actualizar.py)
        for a in json.loads(ruta_avisos.read_text(encoding="utf-8")):
            errores.append(a)
            con_error[a["universidad"]] = True
    sin_listado = dict(ESTADOS_SIN_LISTADO)
    for u in inventario:  # privadas sin página de cátedras localizada
        if u.get("titularidad") == "Privada" and not u["url_catedras"]:
            sin_listado[u["universidad"]] = u["notas"]
    for sig, texto_aviso in sin_listado.items():
        errores.append({"universidad": sig, "tipo": "Sin listado", "detalle": texto_aviso})
    for sig, texto_aviso in AVISOS.items():
        errores.append({"universidad": sig, "tipo": "Aviso", "detalle": texto_aviso})
    for sig, texto_aviso in ENLACES_ROTOS.items():
        errores.append({"universidad": sig, "tipo": "Enlaces", "detalle": texto_aviso})
    errores.sort(key=lambda e: e["universidad"])
    guardar(salida / "errores.csv", errores, ["universidad", "tipo", "detalle"])

    # Estado en el inventario.
    for u in inventario:
        sig = u["universidad"]
        u["n_registros"] = len(todas.get(sig, []))
        u["ultima_captura"] = fecha if sig in todas else ""
        u["estado"] = "SIN LISTADO" if sig in sin_listado else ("ERROR" if sig in con_error else ("AVISO" if sig in AVISOS else "OK"))
    campos = list(inventario[0])
    with open(RAIZ / "universidades.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(inventario)

    print("Registros:", sum(len(v) for v in todas.values()))
    print("Posibles no capturadas:", len(faltan))
    print("Datos que no aparecen en origen:", len(sospechosos))
    print("Casi repetidas:", len(casi))
    print("Posibles compartidas:", len(compartidas))
    print("Muestra:", len(muestra))


if __name__ == "__main__":
    main()
