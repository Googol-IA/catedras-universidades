"""Compara una captura con la anterior y aplica las reglas contra falsos avisos. No usa IA.

Reglas (ver CLAUDE.md):
1. Si una web falla o no da registros, sus datos anteriores se conservan y no hay bajas.
2. Si una universidad cae más de un 30 %, no se aplica ninguna baja: se pide revisión.
3. Una baja solo se confirma si la cátedra falta en 2 capturas de días distintos.
4. Se compara por clave_normalizada, así que el formato del nombre no cuenta como cambio.
Además, si desaparece una cátedra y aparece otra de nombre muy parecido, se avisa de
«posible cambio de nombre» en lugar de una baja y un alta.
"""
import difflib

from comun import COLUMNAS

CAMPOS_VIGILADOS = ["director", "web", "email", "entidad_colaboradora"]
UMBRAL_CAIDA = 0.70
UMBRAL_PARECIDO = 0.85
NOTAS_AUTOMATICAS = ("Mismo nombre en", "Interuniversitaria según", "Menciona a", "No aparece en la última revisión")


def _cambio(fecha, f, tipo, campo=None, antes=None, ahora=None):
    return {"fecha": fecha, "universidad": f["universidad"], "nombre": f["nombre"], "tipo_cambio": tipo,
            "campo": campo, "valor_anterior": antes, "valor_nuevo": ahora}


def _conservar(f, fecha_anterior, nota=None):
    """Prepara una fila anterior para seguir en la lista, sin arrastrar notas que se recalculan."""
    fila = dict.fromkeys(COLUMNAS) | f
    fila["fecha_captura"] = fila.get("fecha_captura") or fecha_anterior
    notas = [n for n in (fila.get("observaciones") or "").split(" · ") if n and not n.startswith(NOTAS_AUTOMATICAS)]
    if nota:
        notas.append(nota)
    fila["observaciones"] = " · ".join(notas) or None
    return fila


def _parecido(a, b):
    return difflib.SequenceMatcher(None, a.split("|", 1)[1], b.split("|", 1)[1]).ratio()


def comparar(previas, fecha_previa, nuevas, fallos, fecha, pendientes, siglas):
    """Devuelve (filas finales por universidad, cambios, pendientes nuevos, avisos)."""
    finales, cambios, avisos = {}, [], []
    pendientes_nuevos = {}
    for sig in siglas:
        antes = {f["clave_normalizada"]: f for f in previas if f["universidad"] == sig}
        lista = nuevas.get(sig) or []
        if sig in fallos or not lista:
            if antes:
                finales[sig] = [_conservar(f, fecha_previa) for f in antes.values()]
                motivo = fallos.get(sig, "no se encontró ningún registro")
                avisos.append({"universidad": sig, "tipo": "Error", "detalle": f"No se pudo actualizar ({motivo}): se mantienen los datos del {fecha_previa}."})
                pendientes_nuevos.update({k: v for k, v in pendientes.items() if k in antes})
            continue

        ahora = {f["clave_normalizada"]: f for f in lista}
        altas = [k for k in ahora if k not in antes]
        faltan = [k for k in antes if k not in ahora]
        filas = list(ahora.values())

        # Modificaciones en las que siguen.
        for k in ahora:
            if k in antes:
                for campo in CAMPOS_VIGILADOS:
                    viejo, nuevo = antes[k].get(campo) or None, ahora[k].get(campo) or None
                    if viejo != nuevo:
                        cambios.append(_cambio(fecha, ahora[k], "Modificación", campo, viejo, nuevo))

        # Regla 2: caída grande. Nada se da de baja hasta que alguien lo revise.
        if antes and len(ahora) < UMBRAL_CAIDA * len(antes):
            filas += [_conservar(antes[k], fecha_previa) for k in faltan]
            for k in altas:
                cambios.append(_cambio(fecha, ahora[k], "Alta"))
            avisos.append({"universidad": sig, "tipo": "Error",
                           "detalle": f"Sus registros caen de {len(antes)} a {len(ahora)}: no se aplican bajas hasta revisarlo. Puede que su web haya cambiado."})
            pendientes_nuevos.update({k: v for k, v in pendientes.items() if k in faltan})
            finales[sig] = filas
            continue

        # Posibles cambios de nombre.
        for k in list(faltan):
            mejor = max(altas, key=lambda a: _parecido(k, a), default=None)
            if mejor and _parecido(k, mejor) >= UMBRAL_PARECIDO:
                cambios.append(_cambio(fecha, ahora[mejor], "Posible cambio de nombre", "nombre", antes[k]["nombre"], ahora[mejor]["nombre"]))
                faltan.remove(k)
                altas.remove(mejor)

        for k in altas:
            if k not in pendientes:  # si solo faltó una vez, su vuelta no es una novedad
                cambios.append(_cambio(fecha, ahora[k], "Alta"))

        # Regla 3: dos capturas de días distintos para confirmar una baja.
        for k in faltan:
            desde = pendientes.get(k)
            if desde and desde != fecha:
                cambios.append(_cambio(fecha, antes[k], "Baja"))
                continue
            if not desde:
                cambios.append(_cambio(fecha, antes[k], "Posible baja"))
            pendientes_nuevos[k] = desde or fecha
            filas.append(_conservar(antes[k], fecha_previa, f"No aparece en la última revisión ({desde or fecha}); se confirmará en la siguiente"))
        finales[sig] = filas
    return finales, cambios, pendientes_nuevos, avisos
