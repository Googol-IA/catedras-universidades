"""Un extractor por universidad. Cada función recibe una Universidad y devuelve sus filas.

Criterios comunes:
- El nombre se guarda como aparece en la web, aunque no lleve la palabra «Cátedra».
- `web` es el enlace propio que da el listado para esa cátedra (su web o su ficha).
- `entidad_colaboradora` solo se rellena si la web la indica como tal; nunca se deduce del nombre.
"""
import datetime
import json
import re

from comun import limpiar, texto

ES_CATEDRA = re.compile(r"^\W*(c[áàa]tedra|aula|aules)\b", re.I)
NO_SON = re.compile(r"\baula (virtual|global|digital|de empleo)\b", re.I)


def es_catedra(nombre):
    return bool(nombre) and bool(ES_CATEDRA.match(nombre)) and not NO_SON.search(nombre)


def enlaces(u, css, n=1, filtro=es_catedra):
    """Lista sencilla: cada enlace es una cátedra y su texto es el nombre."""
    filas = []
    for a in u.sopa(n).select(css):
        nombre = texto(a)
        if filtro is None or filtro(nombre):
            filas.append(u.fila(nombre, n=n, web=u.enlace(a.get("href"), n)))
    return filas


def unir_sin_duplicar(filas, nuevas, genericas=frozenset()):
    """Añade filas de otro listado. Si ya existe con otra redacción, solo completa sus datos vacíos."""
    palabras = lambda f: set(f["clave_normalizada"].split("|", 1)[1].split()) - genericas  # noqa: E731
    for nueva in nuevas:
        pn = palabras(nueva)
        # También cuenta como la misma si solo cambian los espacios: «Bida Farma» y «Bidafarma».
        previa = next((f for f in filas if pn and palabras(f) and (
            pn <= palabras(f) or palabras(f) <= pn or "".join(sorted(pn)) == "".join(sorted(palabras(f))))), None)
        if previa is None:
            filas.append(nueva)
        else:
            for campo, valor in nueva.items():
                if valor and not previa.get(campo):
                    previa[campo] = valor
    return filas


def etiquetado(contenedor, etiqueta):
    """Busca «Etiqueta: valor» en el texto de un bloque."""
    for e in contenedor.find_all(["li", "p", "div"]):
        m = re.match(rf"\s*{etiqueta}\s*:?\s*(.+)", e.get_text(" "), re.I | re.S)
        if m:
            return limpiar(m.group(1))
    return None


# ---------- Andalucía ----------
def ual(u):
    return [u.fila(texto(c.h3), web=u.enlace(c.select_one("a.btn")["href"]) if c.select_one("a.btn") else None)
            for c in u.sopa().select("div.media.box-info")]


def uca(u):
    return enlaces(u, "ul.ucaGallery li.mv_item h3.mainTitle a", filtro=None)


def uco(u):
    filas = []
    for li in u.sopa().select("ol.distribuidor li"):
        a = li.find("a", href=True)
        filas.append(u.fila(texto(li), web=u.enlace(a["href"]) if a else None))
    # Listado de Transferencia: añade responsable y las cátedras que no estén en el principal.
    nuevas = []
    for tr in u.sopa(2).find("table").find_all("tr")[1:]:
        celdas = tr.find_all("td")
        if len(celdas) >= 6:
            a = celdas[0].find("a", href=True)
            nuevas.append(u.fila(texto(celdas[0]), n=2, tipo="Cátedra", director=texto(celdas[5]),
                                 web=u.enlace(a["href"], 2) if a else None))
    unir_sin_duplicar(filas, nuevas, frozenset({"uco", "catedra", "universidad", "cordoba"}))
    # Aulas de Proyección Social y Cultural.
    for tr in u.sopa(3).find_all("tr"):
        celdas = tr.find_all("td")
        nombre = texto(celdas[0]) if celdas else None
        if nombre and re.match(r"aula\s", nombre, re.I):
            web = next((e["href"] for e in tr.find_all("a", href=True) if "web" in e.get_text().lower()), None)
            filas.append(u.fila(nombre, n=3, tipo="Aula", web=u.enlace(web, 3)))
    return filas


def ugr(u):
    filas = enlaces(u, "article h3.entry-title a", filtro=None)
    nuevas = []
    for c in u.sopa(2).select(".card-main-title"):
        a = c.find_parent("a", href=True)
        nuevas.append(u.fila(texto(c), n=2, web=u.enlace(a["href"], 2) if a else None))
    return unir_sin_duplicar(filas, nuevas, frozenset({"ugr", "catedra", "universidad", "granada"}))


def uhu(u):
    return [f for f in enlaces(u, "a.nav-link[href]") if f["web"] and "catedras-externas" in f["web"]]


def uja(u):
    filas = []
    for n in (1, 2, 3):
        for a in u.sopa(n).select("a:has(h3.vertical-centered)"):
            filas.append(u.fila(texto(a.select_one("h3")), n=n, tipo="Aula" if n == 3 else None, web=u.enlace(a["href"], n)))
    return filas


def uma(u):
    return [f for f in enlaces(u, "a.btn.btn-centro1", filtro=None)
            if f["web"] and ("/catedras/info/" in f["web"] or es_catedra(f["nombre"]))]


def unia(u):
    filas = []
    for c in u.sopa().select("#catedras .el-item"):
        parrafo = c.select_one(".el-content")
        director = None
        if parrafo and re.search(r"director|dirección", parrafo.get_text(), re.I):
            fuerte = parrafo.find("strong")
            director = texto(fuerte)
        a = c.select_one("a.el-link")
        filas.append(u.fila(texto(c.select_one("h3")), director=director, descripcion=texto(parrafo),
                            web=u.enlace(a["href"]) if a else None))
    return filas


def upo(u):
    filas = []
    for a in u.sopa().select("a.accordion-toggle"):
        panel = a.find_parent("div", class_="panel")
        cuerpo = panel.select_one("div.contentblock-texto") if panel else None
        parrafo = next((p for p in (cuerpo.find_all("p") if cuerpo else []) if len(p.get_text(strip=True)) > 40), None)
        filas.append(u.fila(texto(a), descripcion=texto(parrafo)))
    return filas


def us(u):
    filas = []
    for dt in u.sopa().select("dl.ckeditor-accordion > dt"):
        dd = dt.find_next_sibling("dd")
        campos = {}
        for li in dd.select("li"):
            fuerte = li.find("strong")
            if fuerte:
                etiqueta = fuerte.get_text().lower()
                valor = re.sub(r"^\s*(Patrocinador(es)?|Director/a|Sede|Año de creación)\s*:?\s*", "", li.get_text(" "), flags=re.I)
                valor = limpiar(valor.replace(fuerte.get_text(), "", 1) if fuerte.get_text() in valor else valor)
                valor = valor.lstrip(": ").rstrip(" .") if valor else valor
                if "patrocinador" in etiqueta:
                    campos["entidad_colaboradora"] = valor
                elif "director" in etiqueta:
                    # Tras el nombre viene su cargo: «Nombre , Catedrático de…»
                    campos["director"] = limpiar(valor.split(",")[0]) if valor else valor
                elif "sede" in etiqueta:
                    campos["campus_centro"] = valor
                elif "correo" in etiqueta or "e-mail" in etiqueta or "email" in etiqueta:
                    campos["email"] = valor
        web = next((a["href"] for a in dd.select("p a[href]") if a["href"].startswith("http")), None)
        parrafo = next((p for p in dd.find_all("p") if len(p.get_text(strip=True)) > 40), None)
        filas.append(u.fila(texto(dt), web=web, descripcion=texto(parrafo), **campos))
    return filas


# ---------- Aragón, Asturias, Canarias, Cantabria ----------
def unizar(u):
    filas = []
    for c in u.sopa().select("div.views-view-responsive-grid__item"):
        a = c.select_one("div.views-field-title a")
        if a:
            filas.append(u.fila(texto(a), web=u.enlace(a["href"]),
                                entidad_colaboradora=texto(c.select_one("div.views-field-field-entidades-colaboradoras-fc"))))
    return filas


def uniovi(u):
    filas = []
    for h4 in u.sopa().select("div.dictionary > h4"):
        lista = h4.find_next_sibling("ul")
        tipo = "Aula" if "aula" in h4.get_text().lower() else "Cátedra"
        for li in lista.find_all("li", recursive=False) if lista else []:
            datos = {texto(dt).rstrip(":").lower(): dt.find_next_sibling("dd") for dt in li.select("dt")}
            web = datos.get("web")
            enlace = web.find("a", href=True) if web else None
            filas.append(u.fila(texto(li.h5), tipo=tipo, director=texto(datos.get("dirección")),
                                entidad_colaboradora=texto(datos.get("entidad colaboradora")),
                                web=enlace["href"] if enlace and enlace["href"].startswith("http") else None))
    return filas


def ulpgc(u):
    """Repite las cátedras por años: solo se usa la sección más reciente de «vigentes»."""
    filas = []
    primera = next(h for h in u.sopa().select("h2") if h.get_text().strip().upper().startswith("VIGENTES"))
    for b in u.sopa().select(".ulpgcds-accordion__title"):
        if b.find_previous("h2") is not primera:
            continue
        azul = b.select_one(".color-blue")
        nombre = texto(azul or b)
        cabecera = b.find_parent("h3")
        panel = cabecera.find_next_sibling() if cabecera else None
        contenido = limpiar(panel.get_text(" ")) or "" if panel else ""
        fin = r"(?=\s*\.?\s*(?:Director|Responsable|Contacto|Convenio|Acuerdo|Página|Memoria|Promotor|$))"
        promotor = re.search(r"Promotor(?:es)?\s*:\s*(.+?)" + fin, contenido)
        director = re.search(r"Director[a]?(?:\s+\w+)?\s*:\s*(.+?)" + fin, contenido)
        web = next((a["href"] for a in (panel.find_all("a", href=True) if panel else []) if "web" in a.get_text().lower()), None)
        filas.append(u.fila(nombre, tipo="Cátedra", web=u.enlace(web),
                            entidad_colaboradora=limpiar(promotor.group(1)) if promotor else None,
                            director=limpiar(director.group(1)) if director else None))
    return filas


def ull(u):
    filas = []
    for h in u.sopa().select("h2.stk-block-heading__text"):
        nombre = texto(h)
        if not es_catedra(nombre):
            continue
        bloque = h.parent.parent
        web = None
        for a in bloque.find_all("a"):
            if a.get("href") and "web" in a.get_text().lower():
                web = a["href"]
        if not web:
            web = next((a["href"] for a in bloque.find_all("a") if a.get("href")), None)
        filas.append(u.fila(nombre, web=web))
    return filas


def unican(u):
    filas = []
    for li in u.sopa().select("div.contenidoInterior ul li"):
        nombre = texto(li)
        if es_catedra(nombre) and len(nombre) < 200:
            a = li.find("a", href=True)
            filas.append(u.fila(nombre, web=u.enlace(a["href"]) if a else None))
    return filas


# ---------- Castilla y León, Castilla-La Mancha ----------
def ubu(u):
    filas = []
    for h2 in u.sopa().select(".news-container h2"):
        contenido = texto(h2)
        if not contenido or not es_catedra(contenido):
            continue
        m = re.match(r"(.+?)\s*\.?\s*\(((?:Convenio|Acuerdo).+)\)\s*\.?\s*$", contenido)
        nombre, convenio = (m.group(1), m.group(2)) if m else (contenido, None)
        lista = h2.find_next_sibling("ul")
        a = h2.find("a", href=True)
        filas.append(u.fila(nombre, observaciones=convenio, web=u.enlace(a["href"]) if a else None,
                            director=etiquetado(lista, r"Director(?:es|as|a)?(?:\s+de la C[aá]tedra)?") if lista else None))
    return filas


def ule(u):
    filas = []
    for a in u.sopa().select("div.field--name-body li a"):
        contenido = texto(a)
        if not es_catedra(contenido):
            continue
        no_activa = re.search(r"\(.*no activa.*\)", contenido, re.I)
        nombre = limpiar(re.sub(r"\(.*no activa.*\)", "", contenido, flags=re.I))
        filas.append(u.fila(nombre, web=u.enlace(a.get("href")), observaciones="La web la indica como no activa" if no_activa else None))
    return filas


def uva(u):
    filas = []
    for c in u.sopa().select("div.tarjetas_lab"):
        nombre = next(c.stripped_strings, None)
        if not es_catedra(nombre):
            continue
        web = None
        for a in c.find_all("a", href=True):
            if "mas-informacion" not in a["href"]:
                web = u.enlace(a["href"])
                break
        ficha = next((u.enlace(a["href"]) for a in c.find_all("a", href=True) if "mas-informacion" in a["href"]), None)
        filas.append(u.fila(nombre, web=web or ficha))
    return filas


def uclm(u):
    filas = []
    for a in u.sopa().select("a[href]"):
        nombre = texto(a)
        if re.search(r"catedrasaulasempresa/", a["href"], re.I) and es_catedra(nombre) \
                and not re.search(r"^(convocatoria|creaci)", nombre, re.I):
            filas.append(u.fila(nombre, web=u.enlace(a["href"])))
    return filas


# ---------- Cataluña ----------
def uab(u):
    return [u.fila(texto(li)) for li in u.sopa().select("main ul li") if es_catedra(texto(li))]


def ub(u):
    filas = []
    for n in (1, 2, 3, 4):
        for h in u.sopa(n).select("h2.main-title"):
            a = h.find("a", href=True)
            bloque = h.parent
            categoria = texto(bloque.select_one(".searh-result-category span"))
            lineas = [limpiar(x) for x in bloque.stripped_strings]
            director = next((l.split(":", 1)[1].strip() for l in lineas if l.lower().startswith("direcció:")), None)
            centro = next((l for l in lineas if re.match(r"(Facultat|Escola|Institut|Departament|Centre)\b", l)), None)
            filas.append(u.fila(texto(a), n=n, tipo="Aula" if categoria == "Aula" else "Cátedra",
                                web=u.enlace(a["href"], n), director=director, campus_centro=centro))
    return filas


def upc(u):
    filas = []
    for a in u.sopa().select("a[href*='catedres-dempresa/']"):
        nombre = texto(a)
        if not es_catedra(nombre):
            continue
        caja = a.find_parent("div", class_="card-body")
        parrafo = caja.find("p") if caja else None
        filas.append(u.fila(nombre, web=u.enlace(a["href"]), descripcion=texto(parrafo)))
    return filas


def upf(u):
    """Solo las vigentes e institucionales: la tabla final son las ya finalizadas."""
    filas = []
    for a in u.sopa().select("a:has(div.titular)"):
        caja = a.select_one("p.text_caixa")
        if caja is None or not es_catedra(texto(caja)):
            continue
        partes = [texto(p) for p in a.select("div.titular p") if texto(p)]
        filas.append(u.fila(" ".join(partes), web=u.enlace(a["href"])))
    return filas


def udg(u):
    filas = []
    for a in u.sopa().select("a[href*='/estructura/catedres/']"):
        m = re.search(r"/estructura/catedres/([^/?#]+)/?$", a["href"])
        nombre = texto(a)
        if m and nombre and m.group(1) not in ("mapa-catedres", "memories"):
            filas.append(u.fila(nombre, tipo="Cátedra", web=u.enlace(a["href"])))
    return filas


def udl(u):
    return enlaces(u, "p > a[href]")


def urv(u):
    return [f for f in enlaces(u, "a[href*='/catedres/']") if "catedres" in (f["web"] or "")]


# ---------- Madrid ----------
def uah(u):
    return enlaces(u, "li.simple.title-desc h4 a")


def uam(u):
    filas = []
    for n in range(1, len(u.urls) + 1):
        if "fuam.es" not in u.url(n):
            continue
        for a in u.sopa(n).select("div.caja_titulo a[href]"):
            filas.append(u.fila(texto(a), n=n, web=a["href"]))
        for a in u.sopa(n).select("a[href*='aulauam50']"):
            filas.append(u.fila(texto(a), n=n, tipo="Aula", web=a["href"]))
    return filas


def uc3m(u):
    return enlaces(u, "li > a[href*=Organismo]")


def ucm(u):
    """PDF con tabla: una cátedra puede ocupar varias líneas de la tabla, que se unen aquí."""
    import pymupdf
    filas, actual = [], None

    def cerrar():
        if not actual:
            return
        nombre = limpiar(" ".join(actual["nombre"]))
        renovacion = nombre.startswith("*")  # el PDF marca así las que están en trámite de renovación
        persona = limpiar(" ".join(actual["director"]))
        filas.append(u.fila(nombre.lstrip("* "), tipo="Cátedra",
                            campus_centro=limpiar(" ".join(actual["centro"])),
                            entidad_colaboradora=limpiar(" ".join(actual["entidad"])),
                            director=None if persona and persona.lower().startswith("pendiente") else persona,
                            descripcion=limpiar(" ".join(actual["objeto"])),
                            observaciones="En trámite de renovación según el PDF" if renovacion else None))

    with pymupdf.open(stream=u.sopa(1), filetype="pdf") as pdf:
        for pagina in pdf:
            for tabla in pagina.find_tables().tables:
                datos = tabla.extract()
                cabecera = [limpiar(c) or "" for c in datos[0]]
                if not cabecera[0].upper().startswith("TÍTULO"):
                    continue  # tablas sin cabecera: columnas desconocidas
                col = {nom: next(i for i, c in enumerate(cabecera) if c.upper().startswith(nom))
                       for nom in ("CENTRO", "ENTIDAD", "DOTACIÓN", "DIRECCIÓN", "OBJETO")}
                for f in datos[1:]:
                    celdas = [limpiar(c) or "" for c in f]
                    # El nombre puede caer en cualquiera de las columnas anteriores a «Centro».
                    titulo = " ".join(c for c in celdas[:col["CENTRO"]] if c)
                    if re.match(r"\*?\s*C[áa]tedra\b", titulo):
                        cerrar()
                        actual = {"nombre": [], "centro": [], "entidad": [], "director": [], "objeto": []}
                    if actual is None:
                        continue
                    actual["nombre"].append(titulo)
                    actual["centro"].append(celdas[col["CENTRO"]])
                    actual["entidad"].append(" ".join(celdas[col["ENTIDAD"]:col["DOTACIÓN"]]))
                    actual["director"].append(celdas[col["DIRECCIÓN"]])
                    actual["objeto"].append(celdas[col["OBJETO"]])
    cerrar()
    return filas


def upm(u):
    hoy = datetime.date.fromisoformat(u.fecha)
    filas = []
    for n, sopa in u.todas("upm"):
        for c in sopa.select(".card:has(h5.card-title)"):
            a = c.select_one("h5.card-title a")
            director = c.select_one("p.card-text a")
            fechas = re.findall(r"\d{2}/\d{2}/\d{4}", texto(c.select_one(".badge")) or "")
            aviso = None
            if len(fechas) == 2:
                fin = datetime.datetime.strptime(fechas[1], "%d/%m/%Y").date()
                if fin < hoy:
                    aviso = f"Según la web terminó el {fechas[1]}"
            filas.append(u.fila(texto(a), tipo="Cátedra", web=u.enlace(a["href"]) if a else None,
                                director=texto(director), observaciones=aviso))
    return filas


def urjc(u):
    filas = []
    for t in u.sopa().select("table"):
        datos = {}
        for tr in t.find_all("tr"):
            celdas = tr.find_all("td", recursive=False)
            if len(celdas) >= 2:
                datos[(texto(celdas[0]) or "").rstrip(":").lower()] = celdas[1]
        if "nombre" not in datos:
            continue
        persona = datos.get("director") or datos.get("directora") or datos.get("responsable")
        filas.append(u.fila(texto(datos["nombre"]), tipo="Cátedra", director=texto(persona),
                            entidad_colaboradora=texto(datos.get("entidad financiadora")),
                            descripcion=texto(datos.get("objetivos"))))
    return filas


# ---------- Navarra, Comunidad Valenciana ----------
def upna(u):
    return [f for f in enlaces(u, "article li > a[href]")]


def ua(u):
    filas = []
    for fuerte in u.sopa().select("p > strong"):
        nombre = texto(fuerte)
        if not es_catedra(nombre):
            continue
        parrafo = fuerte.parent
        if nombre.lower().rstrip(":") == "cátedra":  # el nombre sigue fuera de la negrita
            nombre = texto(parrafo)
        director = None
        web = None
        for s in parrafo.find_next_siblings("p"):
            contenido = texto(s) or ""
            if es_catedra(contenido):
                break
            m = re.match(r"Director[a]?\s*:\s*(.+)", contenido)
            if m and not director:
                director = limpiar(m.group(1))
            for a in s.find_all("a", href=True):
                web = web or u.enlace(a["href"])
        filas.append(u.fila(nombre, director=director, web=web))
    return filas


def umh(u):
    filas = []
    for p in u.sopa(1).select("div.page-content-wrap p"):
        nombre = texto(p)
        if es_catedra(nombre):
            a = p.find("a", href=True)
            filas.append(u.fila(nombre, n=1, web=u.enlace(a["href"], 1) if a else None))
    for n in (2, 3):
        filas += enlaces(u, "dt.titulo-datos > a", n=n)
    return filas


def uji(u):
    filas = []
    for n in (1, 2):
        for c in u.sopa(n).select("div.bgCreamGrey div.padding-1"):
            a = c.select_one("p.h4-title a")
            if a is None:
                continue
            direccion = next((p for p in c.find_all("p") if re.match(r"\s*Direcci", p.get_text())), None)
            persona = re.sub(r"^\s*Direcci[oó]n?\s*:?\s*", "", direccion.get_text()) if direccion else None
            filas.append(u.fila(texto(a), n=n, web=u.enlace(a.get("href"), n), director=limpiar(persona)))
    return filas


# ---------- Estatales y resto ----------
def uned(u):
    filas = []
    for c in u.sopa(1).select("div.textocontenido p"):
        nombre = texto(c)
        if es_catedra(nombre) and len(nombre) < 200:
            a = c.find("a", href=True)
            filas.append(u.fila(nombre, web=u.enlace(a["href"]) if a else None))
    for s in u.sopa(2).select("div.panel-title span"):
        nombre = texto(s)
        if es_catedra(nombre):
            filas.append(u.fila(nombre, n=2))
    return filas


def unex(u):
    """Datos abiertos en JSON (su CSV trae las columnas descuadradas)."""
    datos = json.loads(u.sopa(2).decode("utf-8-sig", "replace"))
    filas = []
    for b in datos["results"]["bindings"]:
        r = {clave: valor.get("value") for clave, valor in b.items()}
        filas.append(u.fila(r["foaf_name"], n=2, director=limpiar(r.get("directorCatedra")),
                            entidad_colaboradora=limpiar(r.get("ou_entidadPatrocinadora")),
                            web=u.enlace("https://" + r["vcard_url"].strip() if r.get("vcard_url") and "://" not in r["vcard_url"] else r.get("vcard_url"), 2),
                            email=limpiar(r.get("schema_email")),
                            descripcion=limpiar(r.get("dcterms_descripcion")),
                            observaciones="Datos abiertos de la UEx: pueden estar desactualizados"))
    return filas


def udc(u):
    return [f for f in enlaces(u, "p a[href]")]


def usc(u):
    filas = []
    for seccion in u.sopa().select("section.org-tier"):
        titulo = texto(seccion.select_one("h2.tier-title")) or ""
        if not titulo.lower().startswith("cátedras"):
            continue
        for art in seccion.select("article"):
            a = art.select_one("a.banner-link")
            filas.append(u.fila(texto(art.select_one("h2.at-title")), tipo="Cátedra",
                                web=u.enlace(a["href"]) if a else None,
                                observaciones="Cátedra participada por la USC" if "participadas" in titulo.lower() else None))
    return filas


def uvigo(u):
    filas = []
    for h in u.sopa().select("h3.collapsible-item-title"):
        # El panel es el desplegable que viene justo después del título (algunos repiten identificador).
        panel = h.find_next(lambda t: (t.get("id") or "").startswith("collapseCollapsible"))
        lineas = [limpiar(x) for x in panel.stripped_strings] if panel else []

        def tras(*etiquetas):
            for i, linea in enumerate(lineas[:-1]):
                if linea.rstrip(":").lower() in etiquetas:
                    return lineas[i + 1]
            return None

        web = next((e["href"] for e in (panel.find_all("a", href=True) if panel else []) if e["href"].startswith("http")), None)
        filas.append(u.fila(tras("denominación") or texto(h), tipo="Cátedra", web=web,
                            entidad_colaboradora=tras("entidad", "entidades"),
                            director=(tras("dirección", "director", "directora") or "").split(",")[0] or None))
    return filas


def uib(u):
    return enlaces(u, ".journal-content-article li a[href]")


def unirioja(u):
    filas = enlaces(u, "a[href*='catedras-y-aulas-universitarias/']")
    filas += enlaces(u, "a[href*='unescour']")
    return filas


def ehu(u):
    filas = []
    for fig in u.sopa(1).select("figure.row"):
        nombre = texto(fig.select_one("p.card-title"))
        parrafos = [p for p in fig.select("figcaption p") if "card-title" not in (p.get("class") or [])]
        a = fig.find_parent("a", href=True)
        filas.append(u.fila(nombre, n=1, web=u.enlace(a["href"], 1) if a else None,
                            descripcion=texto(parrafos[0]) if parrafos else None))
    for s in u.sopa(2).select("span.information"):
        a = s.find_parent("a", href=True)
        filas.append(u.fila(texto(s), n=2, tipo="Aula", web=u.enlace(a["href"], 2) if a else None))
    return filas


def um(u):
    filas = []
    for n in (2, 3, 4, 5, 6):
        for lead in u.sopa(n).select("p.lead"):
            caja = lead.find_parent(lambda t: t.name == "div" and {"card", "flex-parent"} & set(t.get("class", [])))
            nombre = texto(lead)
            if not es_catedra(nombre) or caja is None:
                continue
            director = etiquetado(caja, "(?:Co)?[Dd]irector[a]?")
            a = caja.find("a", href=True)
            filas.append(u.fila(nombre, n=n, director=director, web=u.enlace(a["href"], n) if a else None))
    return filas


def upct(u):
    filas = []
    for a in u.sopa().select("div.accordion-body a[href*='catedra/']"):
        nombre = texto(a) or texto(a.find_parent("div"))
        if nombre:
            filas.append(u.fila(nombre, tipo="Cátedra", web=u.enlace(a["href"])))
    return filas
