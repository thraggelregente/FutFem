"""Ranking de individuales WTA: PDF oficial, validado y persistido.

Una ausencia en la lista nunca se convierte en una posición inventada.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import requests
from pypdf import PdfReader

import utilidades as U

URL = "https://wtafiles.wtatennis.com/pdf/rankings/Singles_Numeric.pdf"
ARCHIVO = "ranking_wta_oficial_v1.json"
MAX_EDAD_DIAS = 14
_cache = U.CacheTTL(6 * 3600)
_MESES = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
_ALIAS = {"catherine mcnally": "caty mcnally"}


def clave_nombre(nombre):
    n = U.normalizar(nombre)
    n = _ALIAS.get(n, n)
    return " ".join(sorted(n.split()))


def parsear_pdf(contenido):
    reader = PdfReader(io.BytesIO(contenido))
    textos = [p.extract_text(extraction_mode="layout") or "" for p in reader.pages]
    texto = "\n".join(textos)
    if "WTA Singles Rankings" not in texto:
        raise ValueError("la lista no corresponde a individuales WTA")
    fechas = re.findall(r"As of:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", texto)
    if not fechas or len(set(fechas)) != 1:
        raise ValueError("fecha de ranking ausente o inconsistente")
    dia, mes, anio = fechas[0]
    fecha = datetime(int(anio), _MESES[mes.lower()], int(dia), tzinfo=timezone.utc)
    jugadoras = {}
    for linea in texto.splitlines():
        m = re.match(r"^\s*(\d+)\s+\([^)]*\)\s+(.+?)\s{2,}(.*)$", linea)
        if not m or "," not in m[2]:
            continue
        apellido, nombre = m[2].split(",", 1)
        campos = m[3].split()
        pais = campos.pop(0) if campos and re.fullmatch(r"[A-Z]{3}", campos[0]) else None
        if not campos or not campos[0].isdigit():
            raise ValueError("fila sin puntos válidos")
        key = clave_nombre(f"{nombre.strip()} {apellido.strip()}")
        if key in jugadoras:
            raise ValueError("nombre ambiguo en el ranking")
        jugadoras[key] = {"ranking": int(m[1]), "puntos": int(campos[0]), "pais": pais}
    ranks = {r["ranking"] for r in jugadoras.values()}
    if (len(jugadoras) < 1000 or max(ranks, default=0) < 1000 or min(ranks, default=0) != 1
            or sum(r["ranking"] <= 150 for r in jugadoras.values()) < 140):
        raise ValueError("ranking incompleto o formato no reconocido")
    return {"fecha": fecha.date().isoformat(), "fuente": "WTA oficial", "jugadoras": jugadoras}


def vigente(snapshot):
    try:
        f = datetime.fromisoformat(snapshot["fecha"]).replace(tzinfo=timezone.utc)
        edad = (datetime.now(timezone.utc) - f).total_seconds() / 86400
        return -1 <= edad <= MAX_EDAD_DIAS and len(snapshot["jugadoras"]) >= 1000
    except (KeyError, TypeError, ValueError):
        return False


def obtener():
    hit, valor = _cache.get("ranking")
    if hit:
        return valor if vigente(valor) else None
    guardado = U.cargar_json(ARCHIVO, {})
    valor = guardado if vigente(guardado) else None
    try:
        respuesta = requests.get(URL, timeout=25)
        respuesta.raise_for_status()
        nuevo = parsear_pdf(respuesta.content)
        if not vigente(nuevo):
            raise ValueError("fecha fuera de vigencia")
        if valor and nuevo["fecha"] < valor["fecha"]:
            raise ValueError("la descarga retrocede la fecha")
        valor = nuevo
        U.guardar_json(ARCHIVO, valor)
        U.log(f"[wta] {len(valor['jugadoras'])} jugadoras; fecha={valor['fecha']}; fuente=WTA oficial")
    except Exception as exc:
        U.log(f"[wta] descarga no validada ({type(exc).__name__}); respaldo={'vigente' if valor else 'no disponible'}")
    _cache.set("ranking", valor, ttl=6 * 3600 if valor else 30 * 60)
    return valor


def enriquecer(eventos, espn=None):
    """Resuelve por nombre exacto/alias verificado, sin comparar IDs de proveedores."""
    snapshot = obtener()
    respaldo = {}
    fecha_respaldo = None
    if snapshot is None and espn is not None:
        espn.ranking_wta()
        fecha_respaldo = getattr(espn, "_ranking_fecha", None)
        try:
            edad = (datetime.now(timezone.utc) - datetime.fromisoformat(fecha_respaldo.replace("Z", "+00:00"))).days
            if 0 <= edad <= MAX_EDAD_DIAS:
                respaldo = {clave_nombre(n): r for n, r in getattr(espn, "_ranking_nombres_completos", {}).items()}
        except (AttributeError, TypeError, ValueError):
            pass
    for ev in eventos:
        if ev.get("deporte") != "Tennis":
            continue
        for lado in ("local", "visita"):
            jugador = ev.get(lado) or {}
            key = clave_nombre(jugador.get("nombre", ""))
            fila = (snapshot or {}).get("jugadoras", {}).get(key)
            jugador.update({"ranking": fila["ranking"] if fila else respaldo.get(key),
                            "ranking_puntos": fila["puntos"] if fila else None,
                            "ranking_fecha": snapshot["fecha"] if fila else fecha_respaldo if key in respaldo else None,
                            "ranking_fuente": "WTA oficial" if fila else "ESPN" if key in respaldo else None,
                            "fuera_ranking": False, "ranking_corte": None})
