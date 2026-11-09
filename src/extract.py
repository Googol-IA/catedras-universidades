"""Convierte lo descargado al esquema común de CLAUDE.md, sin usar IA.

Uso:
    python src/extract.py                         todas, con la captura más reciente
    python src/extract.py UPV UV                  solo esas
    python src/extract.py UPV UV --fecha 2026-11-08

Lee data/raw/FECHA/ y guarda data/parsed/FECHA/<univ>.json. Los extractores de
cada universidad están en extractores.py; lo común, en comun.py.
"""
import csv
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extractores  # noqa: E402
import extractores_privadas  # noqa: E402
from comun import Universidad, limpiar, sin_repetidos, texto  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
# Filas de los listados que no son cátedras.
EXCLUIR_UV = {"Administració General UVCÀTEDRES"}


def extraer_upv(u):
    """UPV: cada cátedra es un bloque con título h5, director, descripción y enlace a su web."""
    filas = []
    fichas = [(titulo, 1, "Cátedra") for titulo in u.sopa(1).find_all("h5", class_="wp-block-heading")]
    fichas += [(titulo, 2, "Aula") for titulo in u.sopa(2).find_all("h5", class_="wp-block-heading")]
    for titulo, pagina, tipo in fichas:
        bloque = titulo.find_parent("div", class_="wp-block-columns")
        if bloque is None:
            continue
        directores, web, web_logo = [], None, None
        for enlace in bloque.find_all("a", href=True):
            if "ficha-personal" in enlace["href"] or "sic_person" in enlace["href"]:  # perfil del director
                nombre = limpiar(enlace.get_text())
                if nombre:
                    directores.append(nombre)
            elif limpiar(enlace.get_text()):  # enlace con el nombre de la cátedra: es su web
                web = web or enlace["href"].strip()
            else:  # enlace en el logo: solo sirve si no hay otro
                web_logo = web_logo or enlace["href"].strip()
        web = web or web_logo
        if not directores:  # director escrito sin enlace
            for p in bloque.find_all("p"):
                m = re.match(r"Direcci[oó]n de C[aá]tedra:\s*(.+)", p.get_text(" ", strip=True))
                if m:
                    directores.append(limpiar(m.group(1)))
                    break
        # Todo el texto de la ficha salvo la línea de dirección (algunas fichas incluyen listas).
        parrafos = [limpiar(p.get_text(" ")) for p in bloque.find_all(["p", "li"])
                    if not re.match(r"\s*(?:Co-?)?[Dd]irecci[oó]n", p.get_text())]
        filas.append(u.fila(limpiar(titulo.get_text()), n=pagina, tipo=tipo,
                            director="; ".join(directores) or None, web=web,
                            descripcion=" ".join(p for p in parrafos if p) or None))
    return filas


def campus_uv(celda):
    """UV: lo que la web indica como campus o centro, sin la palabra «Campus» delante.

    Una calle o un código postal no son un campus: si solo hay eso, se deja vacío.
    """
    for p in celda.find_all("p"):
        contenido = limpiar(p.get_text(" "))
        if not contenido or p.find("span", class_=re.compile("fa-")):
            continue
        if re.match(r"(?:C/|Av\.|Avda|Carrer|Pl\.|Plaça|\d{5}\b)", contenido):
            continue
        return re.sub(r"^Campus\s+(?:de(?:ls?)?\s+)?", "", contenido)
    return None


def extraer_uv(u):
    """UV: tabla con tres columnas (nombre, dirección, web/correo)."""
    filas = []
    for tr in u.sopa().find("table", class_="listable").find_all("tr"):
        celdas = tr.find_all("td")
        if len(celdas) < 3:  # cabecera
            continue
        nombre = texto(celdas[0])
        if nombre in EXCLUIR_UV:
            continue
        icono_web = celdas[2].find("span", class_="fa-globe")
        enlace_web = icono_web.find_next_sibling("a") if icono_web else None
        correo = celdas[2].find("a", href=re.compile(r"^mailto:", re.I))
        filas.append(u.fila(nombre, tipo="Cátedra",
                            web=enlace_web["href"].strip() if enlace_web and enlace_web.has_attr("href") else None,
                            email=correo["href"].split(":", 1)[1].strip() if correo else None,
                            campus_centro=campus_uv(celdas[1])))
    return filas


EXTRACTORES = {
    "UPV": extraer_upv, "UV": extraer_uv,
    "UAL": extractores.ual, "UCA": extractores.uca, "UCO": extractores.uco, "UGR": extractores.ugr,
    "UHU": extractores.uhu, "UJA": extractores.uja, "UMA": extractores.uma, "UNIA": extractores.unia,
    "UPO": extractores.upo, "US": extractores.us, "UNIZAR": extractores.unizar, "UNIOVI": extractores.uniovi,
    "ULPGC": extractores.ulpgc, "ULL": extractores.ull, "UNICAN": extractores.unican, "UBU": extractores.ubu,
    "ULE": extractores.ule, "UVA": extractores.uva, "UCLM": extractores.uclm, "UAB": extractores.uab,
    "UB": extractores.ub, "UPC": extractores.upc, "UPF": extractores.upf, "UDG": extractores.udg,
    "UDL": extractores.udl, "URV": extractores.urv, "UAH": extractores.uah, "UAM": extractores.uam,
    "UC3M": extractores.uc3m, "UCM": extractores.ucm, "UPM": extractores.upm, "URJC": extractores.urjc,
    "UPNA": extractores.upna, "UA": extractores.ua, "UMH": extractores.umh, "UJI": extractores.uji,
    "UNED": extractores.uned, "UNEX": extractores.unex, "UDC": extractores.udc, "USC": extractores.usc,
    "UVIGO": extractores.uvigo, "UIB": extractores.uib, "UNIRIOJA": extractores.unirioja,
    "EHU": extractores.ehu, "UM": extractores.um, "UPCT": extractores.upct,
}


EXTRACTORES.update(extractores_privadas.EXTRACTORES)


class Paginas(Universidad):
    """Universidad cuyas páginas se leen del disco solo cuando se piden."""

    def __init__(self, sigla, carpeta, urls, fecha):
        super().__init__(sigla, {}, urls, fecha)
        self.carpeta = carpeta

    def _leer(self, ruta):
        if ruta.suffix == ".html":
            return BeautifulSoup(ruta.read_bytes(), "html.parser")
        return ruta.read_bytes()

    def sopa(self, n=1):
        if n not in self.paginas:
            base = self.sigla.lower() + ("" if n == 1 else f"_{n}")
            archivos = sorted(self.carpeta.glob(base + ".*"))
            if not archivos:
                raise FileNotFoundError(f"Falta la página {n} de {self.sigla}")
            self.paginas[n] = self._leer(archivos[0])
        return self.paginas[n]

    def todas(self, prefijo):
        """Páginas numeradas por el navegador: <prefijo>.html, <prefijo>_p2.html…"""
        yield 1, self.sopa(1)
        for ruta in sorted(self.carpeta.glob(f"{prefijo}_p*.html"), key=lambda p: int(re.search(r"_p(\d+)", p.name).group(1))):
            yield 1, BeautifulSoup(ruta.read_bytes(), "html.parser")


def urls_inventario():
    with open(RAIZ / "universidades.csv", encoding="utf-8-sig", newline="") as f:
        return {u["universidad"]: [u["url_catedras"]] + [x.strip() for x in u.get("urls_adicionales", "").split("|") if x.strip()]
                for u in csv.DictReader(f, delimiter=";")}


def extraer_todas(fecha, pedidas=None):
    """Extrae cada universidad. Si una falla, las demás siguen. Devuelve (filas, fallos)."""
    urls = urls_inventario()
    origen = RAIZ / "data" / "raw" / fecha
    salida = RAIZ / "data" / "parsed" / fecha
    salida.mkdir(parents=True, exist_ok=True)
    filas, fallos = {}, {}
    for sig in pedidas or list(EXTRACTORES):
        if sig not in EXTRACTORES:
            print(f"{sig}: aún no tiene extractor, se omite")
            continue
        try:
            resultado = sin_repetidos(EXTRACTORES[sig](Paginas(sig, origen, urls[sig], fecha)))
        except FileNotFoundError:
            fallos[sig] = "su web no se pudo descargar"
            print(f"{sig}: FALLO, no se pudo descargar")
            continue
        except Exception as e:  # una web rediseñada no debe parar a las demás
            fallos[sig] = "su página ha cambiado de formato"
            print(f"{sig}: FALLO al extraer ({type(e).__name__}: {e})")
            continue
        if not resultado:
            fallos[sig] = "no se encontró ningún registro en su página"
            print(f"{sig}: FALLO, ningún registro")
            continue
        filas[sig] = resultado
        with open(salida / f"{sig.lower()}.json", "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
        print(f"{sig}: {len(resultado)} registros")
    return filas, fallos


def main():
    args = sys.argv[1:]
    fecha = None
    if "--fecha" in args:
        i = args.index("--fecha")
        fecha = args[i + 1]
        del args[i:i + 2]
    if fecha is None:
        fecha = max(p.name for p in (RAIZ / "data" / "raw").iterdir() if p.is_dir())
    filas, _ = extraer_todas(fecha, [a.upper() for a in args] or None)
    print("Total:", sum(len(v) for v in filas.values()))


if __name__ == "__main__":
    main()
