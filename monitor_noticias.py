"""
monitor_noticias.py
Noticias de último momento (bajas, lesiones, rotaciones) vía RSS de instancias Nitter.
- Solo se consulta para eventos ya calificados como mismatch.
- Solo cuenta publicaciones de las últimas 48 h que mencionen a alguno de los equipos.
- Las instancias Nitter públicas suelen caerse o bloquearse: si ninguna responde,
  el barrido lo deja en el log (fuente "nitter") y la alerta sale igual sin esta sección.
  Podés definir tus instancias con la variable NITTER_INSTANCES (separadas por coma).
"""

import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import utilidades as U

LOCAL = "Local"
VISITA = "Visitante"

# Palabras específicas (se quitaron "subs", "lineup", "alineación", etc.: daban falsos positivos siempre)
PALABRAS_CLAVE_ROTACION = [
    "rotacion", "rotación", "rotaciones", "suplentes", "juveniles", "descanso",
    "bajas", "baja confirmada", "lesion", "lesión", "lesionada", "descartada",
    "no jugará", "no jugara", "ausencia", "rotated", "injury", "injured",
    "ruled out", "doubtful", "rested", "reserves",
]

INSTANCIAS_RSS = [
    i.strip().rstrip("/")
    for i in os.environ.get(
        "NITTER_INSTANCES",
        "https://nitter.net,https://nitter.poast.org,https://nitter.privacydev.net",
    ).split(",")
    if i.strip()
]

HEADERS_NOTICIAS = dict(U.HEADERS_NAVEGADOR, Accept="application/rss+xml, application/xml, text/xml, */*")

_cache = U.CacheTTL(30 * 60)


def _texto(item, etiqueta):
    nodo = item.find(etiqueta)
    return (nodo.text or "") if nodo is not None else ""


def _es_reciente(item, horas=48):
    try:
        f = parsedate_to_datetime(_texto(item, "pubDate"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - f <= timedelta(hours=horas)
    except Exception:
        return False  # sin fecha válida no lo uso


def _equipo_mencionado(contenido_norm, tokens_local, tokens_visita):
    toks = set(contenido_norm.split())
    if tokens_local and tokens_local <= toks:
        return LOCAL
    if tokens_visita and tokens_visita <= toks:
        return VISITA
    return None


def buscar_novedades_partido(equipo_local, equipo_visita):
    """
    Devuelve {alerta_novedad, fragmento, equipo (LOCAL/VISITA), ...}.
    El equipo permite al orquestador saber si la novedad afecta al favorito o a la rival.
    """
    sin_novedad = {"alerta_novedad": False, "tipo": "Sin alertas de última hora", "fragmento": "", "equipo": None}

    clave = f"{equipo_local}|{equipo_visita}"
    hit, valor = _cache.get(clave)
    if hit:
        return valor

    tokens_local = U.tokens_significativos(equipo_local)
    tokens_visita = U.tokens_significativos(equipo_visita)
    query = urllib.parse.quote(f'"{equipo_local}" OR "{equipo_visita}"')

    for instancia in INSTANCIAS_RSS:
        texto = U.get_texto(f"{instancia}/search/rss?f=tweets&q={query}", "nitter",
                            headers=HEADERS_NOTICIAS, timeout=6)
        if not texto or not texto.strip():
            continue

        try:
            root = ET.fromstring(texto)
        except ET.ParseError:
            U.log(f"[nitter] RSS inválido en {instancia}")
            continue

        resultado = sin_novedad
        for item in root.findall(".//item")[:10]:
            if not _es_reciente(item):
                continue
            titulo = _texto(item, "title")
            contenido = f"{titulo} {_texto(item, 'description')}"
            contenido_norm = U.normalizar(contenido)

            equipo = _equipo_mencionado(contenido_norm, tokens_local, tokens_visita)
            if equipo is None:
                continue
            if any(U.normalizar(kw) in contenido_norm for kw in PALABRAS_CLAVE_ROTACION):
                resultado = {
                    "alerta_novedad": True,
                    "tipo": "Novedad de plantel",
                    "fragmento": titulo[:140],
                    "equipo": equipo,
                }
                break

        _cache.set(clave, resultado)
        return resultado

    return sin_novedad
