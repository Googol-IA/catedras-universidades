"""Reglas comunes a todas las universidades: esquema de columnas, clave y ayudas de lectura."""
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

COLUMNAS = [
    "universidad", "nombre", "tipo", "entidad_colaboradora", "director", "web", "email",
    "campus_centro", "url_origen", "fecha_captura", "clave_normalizada", "observaciones", "descripcion",
]
# Palabras que no cuentan al comparar nombres (las mismas que usa el piloto).
PALABRAS_VACIAS = {"de", "del", "la", "el", "i", "y", "en", "a", "per", "para"}


def clave_normalizada(universidad, nombre):
    """Clave para comparar capturas: sin tildes, signos, prefijo «cátedra» ni palabras vacías."""
    # Un apóstrofo o guion tipográfico cuenta igual que el normal: no debe parecer otra cátedra.
    nombre = re.sub(r"[’‘ʼ´`]", "'", nombre)
    nombre = re.sub(r"[–—‐‑−]", "-", nombre)
    # Otros signos (· “ ”) desaparecen sin dejar espacio: Intel·ligència → intelligencia.
    texto = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    palabras = re.sub(r"[^a-z0-9]+", " ", texto).split()
    while palabras and palabras[0] == "catedra":  # la UPV a veces lo repite: «Cátedra Cátedra X»
        palabras.pop(0)
    return f"{universidad.lower()}|" + " ".join(p for p in palabras if p not in PALABRAS_VACIAS)


def limpiar(texto):
    """Quita espacios sobrantes. Devuelve None si no queda nada."""
    # También quita caracteres invisibles que algunas webs dejan dentro de las palabras.
    return " ".join(re.sub("[\u200b\u200c\u200d\u2060\ufeff]", "", texto or "").split()) or None


def texto(elemento, separador=" "):
    return limpiar(elemento.get_text(separador)) if elemento is not None else None


def tipo_por_nombre(nombre):
    return "Aula" if re.match(r"\W*(aula|aules)\b", nombre, re.I) else "Cátedra"


def limpiar_web(web):
    """Quita códigos de sesión, que cambian en cada visita, y descarta enlaces sin dominio válido."""
    if not web:
        return None
    web = re.sub(r";jsessionid=[^?#]*", "", web.strip(), flags=re.I)
    dominio = urlsplit(web).netloc
    return web if "." in dominio else None


class Universidad:
    """Lo que necesita el extractor de una universidad: sus páginas y cómo crear filas."""

    def __init__(self, sigla, paginas, urls, fecha):
        self.sigla, self.paginas, self.urls, self.fecha = sigla, paginas, urls, fecha

    def sopa(self, n=1):
        return self.paginas[n]

    def url(self, n=1):
        return self.urls[n - 1]

    def enlace(self, href, n=1):
        """Convierte un enlace en dirección completa. Ignora anclas, correos y enlaces vacíos."""
        href = (href or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return None
        return urljoin(self.url(n), href)

    def fila(self, nombre, n=1, tipo=None, **campos):
        nombre = limpiar(nombre)
        datos = dict.fromkeys(COLUMNAS)
        datos.update(universidad=self.sigla, nombre=nombre, tipo=tipo or tipo_por_nombre(nombre),
                     url_origen=self.url(n), fecha_captura=self.fecha,
                     clave_normalizada=clave_normalizada(self.sigla, nombre))
        # Un valor sin letras ni números («---») es lo mismo que no constar.
        datos.update({k: v for k, v in campos.items() if v and re.search(r"\w", str(v))})
        datos["web"] = limpiar_web(datos["web"])
        return datos


def sin_repetidos(filas):
    """Deja cada cátedra una vez y conserva los datos que solo traiga la repetida."""
    vistos = {}
    for f in filas:
        previa = vistos.setdefault(f["clave_normalizada"], f)
        if previa is not f:
            for campo in COLUMNAS:
                if not previa[campo] and f[campo]:
                    previa[campo] = f[campo]
    return list(vistos.values())
