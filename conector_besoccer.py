"""
conector_besoccer.py
Eventos de fútbol FEMENINO de ascenso y formativas vía BeSoccer:
- Regionales, ascenso (2da/3ra división) y formativas (Sub-19/20).
- Monitoreo de alineaciones confirmadas para detectar rotaciones tempranas.

Nota: los endpoints de BeSoccer no son una API oficial documentada. Si dejan de
responder, el radar lo muestra en el resumen de cada barrido (fuente "besoccer").
"""

import re

import utilidades as U

LOCAL = "Local"
VISITA = "Visitante"

HEADERS_BESOCCER = dict(U.HEADERS_NAVEGADOR, Referer="https://es.besoccer.com/")

# 1) Tiene que ser FEMENINO...
#    (el texto se normaliza antes: sin tildes ni signos, "(W)" queda como "w")
_RE_FEMENINO = re.compile(
    r"\b(femenino|femenina|femenil|femeni|feminin|feminine|femminile|women|womens|"
    r"ladies|dames|frauen|damen|fem|w)\b"
)

# 2) ...Y ser ascenso / formativas / regional (las ligas top las cubre Sofascore)
_RE_CATEGORIA = re.compile(
    r"sub[- ]?(19|20|17|21)|\bu[- ]?(19|20|17|21)\b|segunda|tercera|2\.? division|"
    r"primera federacion|primera b|primera c|primera nacional|liga b|serie b|serie c|"
    r"ascenso|reserva|juvenil|regional|division de honor|cadete"
)

_ESTADOS_NO_VIGENTES = ("final", "finaliz", "terminad", "suspend", "aplaz", "cancel", "abandon")


def obtener_partidos_ascenso_besoccer():
    """Partidos del día de ascenso y formativas femeninas (femenino AND categoría)."""
    hoy = U.fecha_arg()
    url = f"https://es.besoccer.com/scripts/bigdata/matches_day.php?date={hoy}"
    data = U.get_json(url, "besoccer", headers=HEADERS_BESOCCER, timeout=12)
    if data is None:
        return []

    matches = data.get("matches", []) if isinstance(data, dict) else data
    partidos = []

    for m in matches or []:
        if not isinstance(m, dict):
            continue
        texto = U.normalizar(
            f"{m.get('league_name') or ''} {m.get('home_team_name') or ''} {m.get('away_team_name') or ''}"
        )

        if not _RE_FEMENINO.search(texto):
            continue
        if not _RE_CATEGORIA.search(texto):
            continue

        estado = m.get("status_name") or "No empezado"
        if any(k in estado.lower() for k in _ESTADOS_NO_VIGENTES):
            continue

        match_id = m.get("id")
        if not match_id:
            continue

        partidos.append({
            "id": f"besoccer_{match_id}",
            "torneo": m.get("league_name", "Torneo Ascenso Fem"),
            "local": m.get("home_team_name", "Local"),
            "visita": m.get("away_team_name", "Visitante"),
            "horario": f"{m.get('hour', 'A confirmar')} (hora BeSoccer)",
            "estado": estado,
            "tiene_alineaciones": bool(m.get("has_lineups", False)),
        })

    return partidos


def _dorsal(jugadora):
    try:
        return int(jugadora.get("dorsal") or jugadora.get("number") or 0)
    except (TypeError, ValueError):
        return 0


def verificar_rotacion_plantel(match_id, umbral_dorsal=28, minimo_jugadoras=4):
    """
    Si hay alineaciones, evalúa rotación por cantidad de titulares con dorsal alto
    (heurística: dorsales > 28 suelen ser juveniles / reserva).
    Devuelve 'lado_rota' = LOCAL / VISITA / None. Si rotan ambos no hay ventaja clara.
    """
    base = {"alineaciones_disponibles": False, "alerta_rotacion": False, "lado_rota": None}
    if not match_id:
        return base

    data = U.get_json(
        f"https://es.besoccer.com/scripts/bigdata/lineups.php?id={match_id}",
        "besoccer", headers=HEADERS_BESOCCER, timeout=8,
    )
    if not isinstance(data, dict):
        return base

    titulares_local = data.get("home_lineup") or []
    titulares_visita = data.get("away_lineup") or []
    if not titulares_local or not titulares_visita:
        return base

    altos_local = sum(1 for j in titulares_local if _dorsal(j) > umbral_dorsal)
    altos_visita = sum(1 for j in titulares_visita if _dorsal(j) > umbral_dorsal)
    rota_local = altos_local >= minimo_jugadoras
    rota_visita = altos_visita >= minimo_jugadoras

    lado = None
    if rota_local and not rota_visita:
        lado = LOCAL
    elif rota_visita and not rota_local:
        lado = VISITA

    return {
        "alineaciones_disponibles": True,
        "alerta_rotacion": lado is not None,
        "lado_rota": lado,
        "dorsales_reserva_local": altos_local,
        "dorsales_reserva_visita": altos_visita,
    }
