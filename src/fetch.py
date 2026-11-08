"""Descarga las páginas de cátedras de cada universidad y las guarda sin modificar.

Uso:
    python src/fetch.py UPV UV      descarga esas universidades
    python src/fetch.py             descarga todas las de universidades.csv

Guarda en data/raw/AAAA-MM-DD/:
    <univ>.html        página principal (url_catedras)
    <univ>_2.html ...  páginas adicionales (urls_adicionales)
    _registro.csv      resultado de cada descarga

Primero intenta una descarga simple. Si falla o si la universidad está marcada
con metodo_descarga=navegador, usa un navegador real. Nunca se desactiva la
comprobación de certificados. No se usa ninguna IA.
"""
import csv
import datetime
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
INVENTARIO = RAIZ / "universidades.csv"
MINIMO_BYTES = 2000  # menos que esto se considera "muy poco contenido" (regla 1)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
CABECERAS = {"User-Agent": UA, "Accept-Language": "es,ca;q=0.8"}
CAMPOS_REGISTRO = ["universidad", "url", "archivo", "metodo", "estado", "bytes"]
# Webs paginadas sin cambiar de dirección: orden para pedir la página n y qué tarjeta vigilar.
PAGINADAS = {"UPM": ("pagina_proys({n})", "h5.card-title")}


def leer_inventario():
    with open(INVENTARIO, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def extension(tipo):
    tipo = (tipo or "").split(";")[0].strip().lower()
    if tipo in ("", "text/html", "application/xhtml+xml"):
        return ".html"
    return mimetypes.guess_extension(tipo) or ".bin"


def descargar_simple(url):
    """Devuelve (contenido, extensión, estado). Si falla, contenido es None."""
    try:
        r = requests.get(url, headers=CABECERAS, timeout=60)
    except requests.RequestException as e:
        return None, None, f"ERROR: {type(e).__name__}"
    if r.status_code != 200:
        return None, None, f"ERROR: HTTP {r.status_code}"
    if len(r.content) < MINIMO_BYTES:
        return None, None, f"ERROR: muy poco contenido ({len(r.content)} bytes)"
    return r.content, extension(r.headers.get("Content-Type")), "OK"


class Navegador:
    """Abre Chromium solo si hace falta y lo reutiliza durante toda la ejecución."""

    def __init__(self):
        self._pw = self._b = self._pagina = None

    def descargar(self, url):
        if self._pagina is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._b = self._pw.chromium.launch()
            self._pagina = self._b.new_context(user_agent=UA, locale="es-ES").new_page()
        try:
            resp = self._pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                self._pagina.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass  # hay webs que nunca dejan de pedir cosas; se guarda lo cargado
            if resp is None or resp.status != 200:
                return None, None, f"ERROR: HTTP {resp.status if resp else 'sin respuesta'}"
            contenido = self._pagina.content().encode("utf-8")
        except Exception as e:
            return None, None, f"ERROR: {type(e).__name__}"
        if len(contenido) < MINIMO_BYTES:
            return None, None, f"ERROR: muy poco contenido ({len(contenido)} bytes)"
        return contenido, ".html", "OK"

    def paginar(self, plantilla, css_tarjeta, carpeta, base):
        """Webs que cambian de página sin cambiar de dirección: pide la 2, la 3… hasta que no haya más."""
        previa = self._pagina.inner_text(css_tarjeta) if self._pagina.query_selector(css_tarjeta) else ""
        n = 2
        while n <= 30:
            self._pagina.evaluate(plantilla.format(n=n))
            self._pagina.wait_for_timeout(2500)
            actual = self._pagina.inner_text(css_tarjeta) if self._pagina.query_selector(css_tarjeta) else ""
            if not actual or actual == previa:
                break
            (carpeta / f"{base}_p{n}.html").write_bytes(self._pagina.content().encode("utf-8"))
            previa = actual
            n += 1
        return n - 2

    def cerrar(self):
        if self._b:
            self._b.close()
            self._pw.stop()


def informar(hechas, total):
    ruta = os.environ.get("LIVE_PROGRESS_FILE")
    if ruta:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"label": "Descargando universidades", "done": hechas, "total": total}, f)


def main():
    pedidas = {s.upper() for s in sys.argv[1:]}
    filas = [u for u in leer_inventario() if not pedidas or u["universidad"].upper() in pedidas]
    faltan = pedidas - {u["universidad"].upper() for u in filas}
    if faltan:
        print("No están en el inventario:", ", ".join(sorted(faltan)))

    fecha = datetime.date.today().isoformat()
    carpeta = RAIZ / "data" / "raw" / fecha
    carpeta.mkdir(parents=True, exist_ok=True)

    navegador = Navegador()
    registro = []
    try:
        for i, u in enumerate(filas):
            sig = u["universidad"]
            if not u["url_catedras"]:
                print(f"{sig}: sin listado, se omite", flush=True)
                registro.append(dict.fromkeys(CAMPOS_REGISTRO, "") | {"universidad": sig, "estado": "SIN LISTADO"})
                continue
            urls = [u["url_catedras"]] + [x.strip() for x in u.get("urls_adicionales", "").split("|") if x.strip()]
            for n, url in enumerate(urls, start=1):
                forzar = u.get("metodo_descarga") == "navegador" and not url.lower().endswith("?ver")
                contenido, ext, estado, metodo = None, None, "", "simple"
                if not forzar:
                    contenido, ext, estado = descargar_simple(url)
                if contenido is None:
                    previo = estado
                    metodo = "navegador"
                    contenido, ext, estado = navegador.descargar(url)
                    if contenido is None and previo:
                        estado = f"{previo} / navegador {estado}"
                archivo = ""
                if contenido is not None:
                    archivo = f"{sig.lower()}{'' if n == 1 else f'_{n}'}{ext}"
                    (carpeta / archivo).write_bytes(contenido)
                print(f"{sig} [{n}/{len(urls)}] {metodo}: {estado}" + (f" ({len(contenido) // 1024} KB)" if contenido else ""), flush=True)
                if contenido is not None and n == 1 and sig in PAGINADAS and metodo == "navegador":
                    try:
                        extra = navegador.paginar(*PAGINADAS[sig], carpeta, sig.lower())
                        print(f"{sig}: {extra} páginas más", flush=True)
                    except Exception as e:
                        print(f"{sig}: no se pudieron leer más páginas ({type(e).__name__})", flush=True)
                registro.append({"universidad": sig, "url": url, "archivo": archivo, "metodo": metodo,
                                 "estado": estado, "bytes": len(contenido or b"")})
                time.sleep(1)
            informar(i + 1, len(filas))
    finally:
        navegador.cerrar()

    ruta_registro = carpeta / "_registro.csv"
    previos = []
    if ruta_registro.exists():
        hechas = {r["universidad"] for r in registro}
        with open(ruta_registro, encoding="utf-8", newline="") as f:
            previos = [dict.fromkeys(CAMPOS_REGISTRO, "") | r for r in csv.DictReader(f) if r["universidad"] not in hechas]
    with open(ruta_registro, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_REGISTRO)
        w.writeheader()
        w.writerows(previos + registro)


if __name__ == "__main__":
    main()
