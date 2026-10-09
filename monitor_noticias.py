"""
monitor_noticias.py
Radar ligero de noticias de último momento y novedades de plantel:
- Consulta feeds abiertos RSS / instancias públicas para X (Twitter).
- Se activa solo para eventos previamente calificados como mismatch.
- Rastrea indicios de rotación, ausencias clave o alineaciones alternativas.
"""

import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime

PALABRAS_CLAVE_ROTACION = [
    "suplentes", "rotacion", "rotación", "juveniles", "bajas", 
    "descanso", "starting xi", "startingxi", "alineacion", "alineación",
    "convocadas", "lineup", "subs", "reserves", "alternate"
]

INSTANCIAS_RSS = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net"
]

HEADERS_NOTICIAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*"
}

def buscar_novedades_partido(equipo_local, equipo_visita):
    """
    Rastrea menciones recientes de ambos equipos buscando alertas de alineación.
    Devuelve si se detectó una bandera de rotación y el texto extraído.
    """
    terminos_busqueda = f'"{equipo_local}" OR "{equipo_visita}"'
    query_encoded = urllib.parse.quote(terminos_busqueda)

    for instancia in INSTANCIAS_RSS:
        url_feed = f"{instancia}/search/rss?f=tweets&q={query_encoded}"
        try:
            r = requests.get(url_feed, headers=HEADERS_NOTICIAS, timeout=6)
            if r.status_code != 200 or not r.text.strip():
                continue

            root = ET.fromstring(r.content)
            items = root.findall(".//item")

            for item in items[:5]:
                titulo = (item.find("title").text or "").lower()
                descripcion = (item.find("description").text or "").lower()
                contenido = f"{titulo} {descripcion}"

                # Detección de palabras clave de plantel
                for kw in PALABRAS_CLAVE_ROTACION:
                    if kw in contenido:
                        return {
                            "alerta_novedad": True,
                            "tipo": "Novedad de Alineación / Plantel",
                            "fragmento": item.find("title").text[:140],
                            "origen": "Redes Oficiales / RSS"
                        }
        except Exception:
            continue

    return {
        "alerta_novedad": False,
        "tipo": "Sin alertas de última hora",
        "fragmento": "",
        "origen": "Sin reportes anómalos"
    }