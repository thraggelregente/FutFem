"""
metricas_profundas.py
MÃ©tricas de apoyo (solo se consultan para eventos que ya son mismatch):
- Tennis Abstract / Sackmann: win rate de la FAVORITA en la superficie del partido.
- ScoreBing: presiÃ³n ofensiva (cÃ³rners) de la favorita en fÃºtbol.
"""

import csv
import io
from datetime import datetime

import utilidades as U

_cache_csv = U.CacheTTL(12 * 3600)
_cache_presion = U.CacheTTL(6 * 3600)

_URL_SACKMANN = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/{archivo}"


# ---------- 1. TENIS: EFECTIVIDAD POR SUPERFICIE ----------
def normalizar_superficie(texto):
    t = (texto or "").lower()
    if "clay" in t:
        return "Clay"
    if "grass" in t:
        return "Grass"
    if "carpet" in t:
        return "Carpet"
    if "hard" in t:
        return "Hard"
    return ""


def _cargar_partidos_wta(anio):
    """Lista de (superficie, ganadora_norm, perdedora_norm). Se cachea 12 h."""
    hit, valor = _cache_csv.get(anio)
    if hit:
        return valor

    filas = []
    for archivo in (f"wta_matches_{anio}.csv", f"wta_matches_qual_itf_{anio}.csv"):
        texto = U.get_texto(_URL_SACKMANN.format(archivo=archivo), "sackmann", timeout=20)
        if not texto:
            continue
        for row in csv.DictReader(io.StringIO(texto)):
            filas.append((
                normalizar_superficie(row.get("surface")),
                U.normalizar(row.get("winner_name")),
                U.normalizar(row.get("loser_name")),
            ))

    if filas:
        _cache_csv.set(anio, filas)
    return filas


def _partir_nombre(nombre):
    """'Swiatek I.' -> (['swiatek'], 'i');  'Iga Swiatek' -> (['iga','swiatek'], None)."""
    tokens = U.normalizar(nombre).split()
    if len(tokens) >= 2 and len(tokens[-1]) == 1:
        return tokens[:-1], tokens[-1]
    return tokens, None


def _es_la_jugadora(nombre_csv_norm, apellido_tokens, inicial):
    toks = nombre_csv_norm.split()
    if not toks or not apellido_tokens:
        return False
    if not all(t in toks for t in apellido_tokens):
        return False
    return inicial is None or toks[0].startswith(inicial)


def consultar_perfil_tenis_abstract(nombre_jugadora, superficie="Hard"):
    """
    Win rate de la jugadora en la superficie indicada (aÃ±o actual + anterior, circuito
    WTA + ITF). Si la superficie no se conoce no marca vulnerabilidad.
    """
    superficie = normalizar_superficie(superficie)
    resultado = {
        "superficie": superficie or "desconocida",
        "efectividad_superficie": "Sin datos suficientes",
        "es_vulnerable_superficie": False,
        "muestras": 0,
    }
    if not superficie or not nombre_jugadora:
        return resultado

    apellido, inicial = _partir_nombre(nombre_jugadora)
    anio = datetime.now().year
    victorias = derrotas = 0

    for a in (anio, anio - 1):
        for sup, ganadora, perdedora in _cargar_partidos_wta(a):
            if sup != superficie:
                continue
            if _es_la_jugadora(ganadora, apellido, inicial):
                victorias += 1
            elif _es_la_jugadora(perdedora, apellido, inicial):
                derrotas += 1

    total = victorias + derrotas
    resultado["muestras"] = total
    if total >= 4:
        win_rate = round(victorias / total * 100, 1)
        resultado["win_rate_superficie"] = win_rate
        resultado["es_vulnerable_superficie"] = win_rate < 40.0
        resultado["efectividad_superficie"] = f"{win_rate}% ({victorias}-{derrotas})"
    return resultado


# ---------- 2. FÃšTBOL: PRESIÃ“N OFENSIVA (SCOREBING) ----------
def obtener_presion_ofensiva_futbol(nombre_equipo):
    """Promedio de cÃ³rners a favor / en contra. Endpoint no oficial: si falla, devuelve ceros."""
    metricas = {"prom_corners_favor": 0.0, "prom_corners_contra": 0.0, "alta_presion": False}
    if not nombre_equipo:
        return metricas

    hit, valor = _cache_presion.get(nombre_equipo)
    if hit:
        return valor

    data = U.get_json("https://www.scorebing.com/ajax/search", "scorebing",
                      params={"q": nombre_equipo}, timeout=8)
    teams = (data or {}).get("teams") if isinstance(data, dict) else None
    team_id = teams[0].get("id") if teams else None
    if not team_id:
        return metricas

    stats_raw = U.get_json("https://www.scorebing.com/ajax/team/corners", "scorebing",
                           params={"team_id": team_id}, timeout=8)
    if isinstance(stats_raw, dict):
        stats = stats_raw.get("recent_corners", {}) or {}
        try:
            favor = float(stats.get("for_avg", 0.0))
            contra = float(stats.get("against_avg", 0.0))
        except (TypeError, ValueError):
            return metricas
        metricas.update({
            "prom_corners_favor": round(favor, 1),
            "prom_corners_contra": round(contra, 1),
            # Alta presiÃ³n: genera >= 6.5 cÃ³rners y concede <= 2.5
            "alta_presion": favor >= 6.5 and contra <= 2.5,
        })
        _cache_presion.set(nombre_equipo, metricas)

    return metricas
