"""Busca el email de cada cátedra en su propia web y en su página de contacto. No usa IA.

La búsqueda a fondo se hace UNA VEZ, en el ordenador, para todas las cátedras:
    python src/emails.py                    busca (si se corta, sigue donde iba) y clasifica
    python src/emails.py --sin-navegador    igual, sin la segunda pasada con navegador real
Guarda en data/emails/: crudo.json (lo visto en cada web) y resultado.json (lo asignado).
Se publica con herramientas/publicar_emails.py.

Después, cada actualización solo busca el email de las cátedras NUEVAS (`aplicar`). Las demás
conservan el que ya tienen: no se vuelven a visitar.

Reglas:
- Solo se visita la web que da el listado de cada cátedra. No se usan buscadores.
- El email que da el propio listado manda: esa cátedra no se visita.
- Si varias cátedras comparten la misma web, esa página no se usa: no se sabría de cuál es el email.
- Una dirección repetida en MINIMO_GENERICO o más cátedras de una universidad, o de nombre claramente
  institucional (info@...), es genérica. Si la cátedra no tiene ninguna propia, se pone la genérica
  que se haya encontrado, marcada como tal en email_tipo.
"""
import collections
import datetime
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "data" / "emails"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
CABECERAS = {"User-Agent": UA, "Accept-Language": "es,ca;q=0.8"}
SEPARADOR = " / "
TIPO_LISTADO, TIPO_WEB, TIPO_GENERICO = "Del listado", "De su web", "Genérico"
MINIMO_GENERICO = 3
MAXIMO_POR_PAGINA = 8  # más que esto es un directorio, no el contacto de una cátedra
MAXIMO_GENERICOS = 2
MAXIMO_CONTACTOS = 2
ESPERA_POR_WEB = 0.5
HILOS = 12
TIEMPO_MAXIMO = 20

EMAIL = re.compile(r"(?<![\w.+-])[a-z0-9][a-z0-9._%+-]*\s?(?:@|\(at\)|\[at\]|\(arroba\)|\[arroba\])\s?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,10}(?![\w-])", re.I)
EXTENSIONES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".css", ".js", ".woff", ".woff2", ".ttf", ".ico", ".map", ".html", ".php")
DOMINIOS_FALSOS = ("example.", "ejemplo.", "domain.", "dominio.", "sentry", "wixpress.", "email.com", "correo.com", "tudominio.", "yourdomain.")
INSTITUCIONAL = re.compile(
    r"^(info|informacion|informacio|information|infouniversidad|comunicacion|comunicacio|prensa|gabinete|rector|rectora|rectorado|"
    r"secretaria|secretariageneral|atencion|contacto|contact|investigacion|investigacio)(\d*)@", re.I)
# Existen, pero no sirven para contactar con una cátedra: ni siquiera como genéricas.
INUTIL = re.compile(
    r"^(webmaster|web|admin|administrador|administracion|noreply|no-reply|donotreply|registro|registre|rgpd|lopd|dpo|dpd|"
    r"protecciondatos|protecciondedatos|proteccion\.datos|privacidad|privacy|sugerencias|cau|soporte|support|ayuda|abuse|postmaster)(\d*)@", re.I)
TEXTO_CONTACTO = re.compile(r"contact|contacte|kontakt|harremanet|qui[eé]nes\s+somos|qui\s+som|equipo|equip\b", re.I)
_ULTIMA = collections.defaultdict(float)
_CERROJOS = collections.defaultdict(threading.Lock)


def _normalizar(texto):
    x = re.sub(r"\s", "", texto).lower()
    return re.sub(r"\(at\)|\[at\]|\(arroba\)|\[arroba\]", "@", x).strip(".")


def correos_de(html):
    """Devuelve las direcciones de una página y la página ya analizada."""
    sopa = BeautifulSoup(html, "html.parser")
    partes = [html, sopa.get_text(" ")]
    for e in sopa.select("[data-cfemail]"):  # direcciones protegidas por Cloudflare
        try:
            b = bytes.fromhex(e["data-cfemail"])
            partes.append("".join(chr(c ^ b[0]) for c in b[1:]))
        except (ValueError, IndexError):
            pass
    for a in sopa.find_all("a", href=True):
        if a["href"].lower().startswith("mailto:"):
            partes.append(unquote(a["href"][7:].split("?")[0]))
    hallados = set()
    for parte in partes:
        for bruto in EMAIL.findall(parte):
            x = _normalizar(bruto)
            if "@" in x and not x.endswith(EXTENSIONES) and not any(d in x.split("@")[1] for d in DOMINIOS_FALSOS):
                hallados.add(x)
    return hallados, sopa


def pedir(url):
    """Descarga simple respetando una espera por web. Devuelve el HTML o None si falla."""
    host = urlparse(url).netloc
    with _CERROJOS[host]:
        espera = _ULTIMA[host] + ESPERA_POR_WEB - time.time()
        if espera > 0:
            time.sleep(espera)
        try:
            r = requests.get(url, headers=CABECERAS, timeout=TIEMPO_MAXIMO)
        except requests.RequestException:
            return None
        finally:
            _ULTIMA[host] = time.time()
    if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "").lower():
        return None
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


class Navegador:
    """Navegador real para webs que solo muestran el contenido con JavaScript."""

    def __init__(self):
        self._pw = self._b = self._p = None

    def __call__(self, url):
        if self._p is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._b = self._pw.chromium.launch()
            self._p = self._b.new_context(user_agent=UA, locale="es-ES").new_page()
        try:
            r = self._p.goto(url, wait_until="domcontentloaded", timeout=30000)
            self._p.wait_for_timeout(2500)
            return self._p.content() if r is not None and r.status == 200 else None
        except Exception:
            return None

    def cerrar(self):
        if self._b:
            self._b.close()
            self._pw.stop()


def visitar(url, pedir_pagina=pedir):
    """Lee la web de la cátedra y sus páginas de contacto. Devuelve lo visto en cada sitio."""
    html = pedir_pagina(url)
    if html is None:
        return {"abierta": False, "web": [], "contacto": []}
    en_web, sopa = correos_de(html)
    en_contacto = set()
    host, vistos = urlparse(url).netloc, {url.split("#")[0]}
    for a in sopa.find_all("a", href=True):
        destino = urljoin(url, a["href"]).split("#")[0]
        if destino in vistos or urlparse(destino).netloc != host:
            continue
        if TEXTO_CONTACTO.search(a.get_text(" ", strip=True)[:40]) or re.search(r"contact", urlparse(destino).path, re.I):
            vistos.add(destino)
            segundo = pedir_pagina(destino)
            if segundo:
                en_contacto |= correos_de(segundo)[0]
            if len(vistos) > MAXIMO_CONTACTOS:
                break
    return {"abierta": True, "web": sorted(en_web), "contacto": sorted(en_contacto - en_web)}


def visitables(filas):
    """Cátedras que se pueden visitar: sin email en el listado y con una web solo suya."""
    usos = collections.Counter((f["universidad"], (f.get("web") or "").rstrip("/")) for f in filas if f.get("web"))
    res = []
    for f in filas:
        web = f.get("web") or ""
        if f.get("email") or not web.lower().startswith("http") or web.lower().split("?")[0].endswith(".pdf"):
            continue
        if usos[(f["universidad"], web.rstrip("/"))] > 1 or web.rstrip("/") == (f.get("url_origen") or "").rstrip("/"):
            continue
        res.append(f)
    return res


def genericos_de(filas, crudo):
    """Direcciones repetidas en varias cátedras de una misma universidad."""
    veces = collections.Counter()
    for f in filas:
        visto = crudo.get(f["clave_normalizada"])
        if visto:
            veces.update((f["universidad"], e) for e in set(visto["web"] + visto["contacto"]))
    res = collections.defaultdict(set)
    for (u, e), n in veces.items():
        if n >= MINIMO_GENERICO:
            res[u].add(e)
    return res


def elegir(visto, genericos_uni):
    """A partir de lo visto en una web, devuelve (email, tipo). Vacío si no hay nada útil."""
    def clasificar(lista):
        utiles = [e for e in lista if not INUTIL.match(e)]
        propios = [e for e in utiles if e not in genericos_uni and not INSTITUCIONAL.match(e)]
        return propios, [e for e in utiles if e not in propios]

    propios_web, genericos_web = clasificar(visto["web"])
    propios_con, genericos_con = clasificar(visto["contacto"])
    propios = propios_web or propios_con
    if propios and len(propios) <= MAXIMO_POR_PAGINA:
        return SEPARADOR.join(propios), TIPO_WEB
    reserva = genericos_web or genericos_con
    if reserva:
        return SEPARADOR.join(reserva[:MAXIMO_GENERICOS]), TIPO_GENERICO
    return None, None


def aplicar(nuevas, previas, genericos):
    """Para cada actualización: copia el email ya conocido y busca solo el de las cátedras nuevas.

    Devuelve cuántas cátedras nuevas se han buscado y en cuántas ha aparecido un email.
    """
    anteriores = {f["clave_normalizada"]: f for f in previas}
    por_buscar = []
    for lista in nuevas.values():
        for f in lista:
            if f.get("email"):
                f["email_tipo"] = TIPO_LISTADO
            elif f["clave_normalizada"] in anteriores:
                previa = anteriores[f["clave_normalizada"]]
                f["email"], f["email_tipo"] = previa.get("email"), previa.get("email_tipo")
            else:
                por_buscar.append(f)
    # La regla de la web compartida se mira con todas las filas, no solo con las nuevas.
    todas = [f for lista in nuevas.values() for f in lista]
    claves = {f["clave_normalizada"] for f in visitables([dict(x, email=None) for x in todas])}
    por_buscar = [f for f in por_buscar if f["clave_normalizada"] in claves]
    navegador, encontrados = Navegador(), 0
    try:
        for f in por_buscar:
            visto = visitar(f["web"])
            if not visto["web"] and not visto["contacto"]:
                visto = visitar(f["web"], navegador)
            f["email"], f["email_tipo"] = elegir(visto, set(genericos.get(f["universidad"], [])))
            encontrados += bool(f["email"])
    finally:
        navegador.cerrar()
    return len(por_buscar), encontrados


# ---------- Búsqueda a fondo, una sola vez ----------
def _informar(texto, hechas, total):
    ruta = os.environ.get("LIVE_PROGRESS_FILE")
    if ruta:
        Path(ruta).write_text(json.dumps({"label": texto, "done": hechas, "total": total}), encoding="utf-8")


def _cargar_filas():
    base = RAIZ / "data" / "parsed"
    ultima = max(p for p in base.iterdir() if p.is_dir())
    filas = []
    for ruta in ultima.glob("*.json"):
        if not ruta.name.startswith("_"):
            filas += json.loads(ruta.read_text(encoding="utf-8"))
    return filas


def busqueda_a_fondo(filas, con_navegador=True):
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA / "crudo.json"
    crudo = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    guardar = lambda: ruta.write_text(json.dumps(crudo, ensure_ascii=False, indent=0), encoding="utf-8")  # noqa: E731
    lista = visitables(filas)

    pendientes = [f for f in lista if f["clave_normalizada"] not in crudo]
    cerrojo, hechas = threading.Lock(), [0]

    def tarea(de_una_web):
        # Cada hilo se ocupa de una web entera: así una web lenta no bloquea a las demás.
        for f in de_una_web:
            visto = visitar(f["web"])
            with cerrojo:
                crudo[f["clave_normalizada"]] = visto | {"pasada": "simple"}
                hechas[0] += 1
                if hechas[0] % 20 == 0:
                    guardar()
                    _informar("Buscando emails", hechas[0], len(pendientes))
                    print(f"{hechas[0]} de {len(pendientes)} webs", flush=True)

    por_web = collections.defaultdict(list)
    for f in pendientes:
        por_web[urlparse(f["web"]).netloc].append(f)
    with ThreadPoolExecutor(HILOS) as grupo:
        list(grupo.map(tarea, por_web.values()))
    guardar()

    if con_navegador:
        vacias = [f for f in lista if not crudo[f["clave_normalizada"]]["web"] and not crudo[f["clave_normalizada"]]["contacto"]
                  and crudo[f["clave_normalizada"]]["pasada"] == "simple"]
        navegador = Navegador()
        try:
            for i, f in enumerate(vacias, start=1):
                visto = visitar(f["web"], navegador)
                previa = crudo[f["clave_normalizada"]]
                visto["abierta"] = visto["abierta"] or previa["abierta"]
                crudo[f["clave_normalizada"]] = visto | {"pasada": "navegador"}
                if i % 10 == 0:
                    guardar()
                    _informar("Buscando emails con navegador", i, len(vacias))
        finally:
            navegador.cerrar()
        guardar()
    return crudo


def clasificar_todo(filas, crudo):
    """Devuelve {clave: {email, email_tipo}} y las direcciones genéricas de cada universidad."""
    genericos = genericos_de(filas, crudo)
    asignados = {}
    for f in filas:
        visto = crudo.get(f["clave_normalizada"])
        if visto and not f.get("email"):
            email, tipo = elegir(visto, genericos.get(f["universidad"], set()))
            if email:
                asignados[f["clave_normalizada"]] = {"email": email, "email_tipo": tipo}
    return asignados, {u: sorted(v) for u, v in genericos.items()}


def main():
    inicio = time.time()
    filas = _cargar_filas()
    crudo = busqueda_a_fondo(filas, "--sin-navegador" not in sys.argv)
    asignados, genericos = clasificar_todo(filas, crudo)
    (CARPETA / "resultado.json").write_text(json.dumps(
        {"fecha": datetime.date.today().isoformat(), "asignados": asignados, "genericos": genericos},
        ensure_ascii=False, indent=1), encoding="utf-8")

    por = collections.defaultdict(collections.Counter)
    for f in filas:
        c, clave = por[f["universidad"]], f["clave_normalizada"]
        c["total"] += 1
        c["listado"] += bool(f.get("email"))
        c["visitadas"] += clave in crudo
        c["abren"] += clave in crudo and crudo[clave]["abierta"]
        tipo = asignados.get(clave, {}).get("email_tipo")
        c["propio"] += tipo == TIPO_WEB
        c["generico"] += tipo == TIPO_GENERICO
    print(f"{'Univ':10}{'Total':>6}{'Listado':>8}{'Visit.':>7}{'Abren':>6}{'Propio':>7}{'Genérico':>9}")
    for u, c in sorted(por.items()):
        print(f"{u:10}{c['total']:6}{c['listado']:8}{c['visitadas']:7}{c['abren']:6}{c['propio']:7}{c['generico']:9}")
    s = sum(por.values(), collections.Counter())
    print(f"{'TOTAL':10}{s['total']:6}{s['listado']:8}{s['visitadas']:7}{s['abren']:6}{s['propio']:7}{s['generico']:9}")
    print(f"Sin ningún email: {s['total'] - s['listado'] - s['propio'] - s['generico']}. Tardó {round((time.time() - inicio) / 60, 1)} minutos.")


if __name__ == "__main__":
    main()
