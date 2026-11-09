"""Extractores de las universidades privadas. Mismos criterios que extractores.py.

No se incluyen observatorios ni otras entidades que aparezcan junto a las cátedras.
"""
import re

from comun import limpiar, texto

ES_CATEDRA = re.compile(r"^\W*(c[áàa]tedr[aá]|aula|aules)\b", re.I)
ES_CATEDRA_PEGADA = re.compile(r"^\W*c[áàa]tedra", re.I)  # «CÁTEDRACHIP»
NO_SON = re.compile(r"\baula (virtual|magna|abierta|de formaci[oó]n)\b", re.I)
RUIDO_ENLACE = re.compile(r"^(c[áàa]tedres?|c[áàa]tedras?|aules?|aulas?)$", re.I)


def _vale(nombre, pegada=False):
    if not nombre or RUIDO_ENLACE.match(nombre) or NO_SON.search(nombre):
        return False
    return bool((ES_CATEDRA_PEGADA if pegada else ES_CATEDRA).match(nombre))


def _web(u, a, n=1):
    href = (a.get("href") or "").strip()
    return u.enlace(href, n) if href and not href.endswith("#") else None


def _por_enlace(u, css, n=1):
    filas = []
    for a in u.sopa(n).select(css):
        nombre = texto(a)
        if _vale(nombre):
            filas.append(u.fila(nombre, n=n, web=_web(u, a, n)))
    return filas


def _tarjetas(u, css, n=1):
    """El enlace envuelve toda la tarjeta: el nombre es el texto alternativo de su imagen o su título."""
    filas = []
    for a in u.sopa(n).select(css):
        img = a.find("img", alt=True)
        titulo = a.find(["h2", "h3", "h4", "h5"])
        nombre = limpiar(titulo.get_text(" ")) if titulo else limpiar(img["alt"]) if img else None
        if _vale(nombre):
            filas.append(u.fila(nombre, n=n, web=_web(u, a, n)))
    return filas


def _titulo_pagina(u, n=1):
    """Página propia de una cátedra: una sola fila con su título."""
    return u.fila(texto(u.sopa(n).find("h1")), n=n, web=u.url(n))


def comillas(u):
    return _tarjetas(u, 'a[class*="styles-module--container"]')


def nebrija(u):
    return _tarjetas(u, 'a[class*="styles-module--container"]')


def ucam(u):
    return _por_enlace(u, 'a[href*="/catedras/"]')


def ucav(u):
    return _por_enlace(u, 'a[href*="/investigacion/catedras/"]')


def uch(u):
    return _por_enlace(u, ".ant-card-meta-title a")


def ucjc(u):
    return _por_enlace(u, 'a[href*="estructura-academica/catedras/"]')


def ucv(u):
    """Cada cátedra es un título h4 seguido de un enlace. Las ocultas en la web no se incluyen."""
    filas = []
    for h in u.sopa().select("h4"):
        if h.find_parent(style=re.compile(r"display:\s*none")):
            continue
        nombre = texto(h)
        if not _vale(nombre):
            continue
        boton = h.find_next("a", string=re.compile("Acceder", re.I))
        siguiente = h.find_next("h4")
        if boton and siguiente and siguiente.sourceline and boton.sourceline and boton.sourceline > siguiente.sourceline:
            boton = None
        filas.append(u.fila(nombre, web=_web(u, boton) if boton else None))
    return filas


def udima(u):
    return _por_enlace(u, 'a[href^="/catedra-"]')


def uemc(u):
    return _por_enlace(u, 'a[href*="/p/catedra-de-"], a[href*="/p/aula-de-"]')


def ufv(u):
    return _por_enlace(u, '[class*="styles_cell"] a[href*="catedras-de-investigacion/"]')


def uic(u):
    filas = []
    for n, _ in enumerate(u.urls, start=1):
        for bloque in u.sopa(n).select(".taxonomy-blocks"):
            nombre = texto(bloque.find("h2"))
            mas = bloque.find("a", class_="more-info")
            if nombre:
                filas.append(u.fila(nombre, n=n, web=_web(u, mas, n) if mas else None))
        for h in u.sopa(n).select("h3"):  # las aulas van en otro formato
            nombre = texto(h)
            if nombre and re.match(r"Aula\b", nombre) and not NO_SON.search(nombre):
                enlace = h.find_next("a", href=re.compile(r"/aules/|/aulas/"))
                filas.append(u.fila(nombre, n=n, tipo="Aula", web=_web(u, enlace, n) if enlace else None))
    return filas


def unav(u):
    filas = []
    for a in u.sopa().select("a.unav-recommended-links__link"):
        nombre = texto(a)
        if _vale(nombre, pegada=True):
            filas.append(u.fila(nombre, web=_web(u, a)))
    return filas


def uoc(u):
    return _por_enlace(u, 'a[href*="/aliances/catedra"], a[href*="/alianzas/catedra"]')


def url(u):
    return _por_enlace(u, '.views-row a[href*="catedres-url/"]')


def usj(u):
    """La web da el nombre sin la palabra «Cátedra», y así se guarda."""
    filas = []
    for a in u.sopa().select('a.c-card-l, .c-card-l a[href*="/investigacion/catedras/"]'):
        titulo = a.find(["h2", "h3", "h4", "h5"])
        nombre = limpiar(titulo.get_text(" ")) if titulo else limpiar(re.sub(r"\s*Ver más\s*$", "", a.get_text(" ")))
        if nombre:
            filas.append(u.fila(nombre, tipo="Cátedra", web=_web(u, a)))
    return filas


def usp(u):
    filas = []
    for h in u.sopa().select("h3"):
        nombre = texto(h)
        if not _vale(nombre):
            continue
        bloque = h.parent
        mas = next((a for a in bloque.find_all("a", href=True) if "más información" in a.get_text(" ").lower()), None)
        filas.append(u.fila(nombre, web=_web(u, mas) if mas else None))
    return filas


def uvic(u):
    filas = []
    for c in u.sopa().select(".card-body"):
        nombre = texto(c.select_one("h4.card-title"))
        if _vale(nombre):
            mas = c.find("a", class_="btn")
            filas.append(u.fila(nombre, web=_web(u, mas) if mas else None))
    return filas


def paginas_propias(u):
    """Sin listado: la web solo tiene páginas sueltas, una por cátedra."""
    return [_titulo_pagina(u, n) for n, _ in enumerate(u.urls, start=1)]


def ie(u):
    """Su página no da el nombre en el h1: se toma del título, tal como aparece."""
    return [u.fila(limpiar(u.sopa().title.get_text().split("|")[0]), web=u.url())]


EXTRACTORES = {
    "COMILLAS": comillas, "NEBRIJA": nebrija, "UCAM": ucam, "UCAV": ucav, "UCH": uch, "UCJC": ucjc, "UCV": ucv, "UDIMA": udima,
    "UEMC": uemc, "UFV": ufv, "UIC": uic, "UNAV": unav, "UOC": uoc, "URL": url, "USJ": usj, "USP": usp, "UVIC": uvic,
    "UEM": paginas_propias, "CUNEF": paginas_propias, "UNEATLANTICO": paginas_propias, "IE": ie,
}
