"""
fuentes_alternativas.py
ITF World Tennis Tour femenino (cuadros oficiales, Wild Cards, rankings).

Se eliminaron `obtener_eventos_aiscore` y `validar_cuota_mercado`: no se usaban en
ningún lado y la validación de cuotas ya la hace tracker_cuotas_smart.

Nota: el endpoint de ITF no es una API oficial documentada. Si deja de responder,
el resumen del barrido lo muestra (fuente "itf").
"""

import re

import utilidades as U

try:
    import motor_mismatches
except Exception as e:  # el orquestador igual avisa si el motor no carga
    motor_mismatches = None
    U.log(f"[itf] no pude importar motor_mismatches: {e}")

HEADERS_ITF = dict(U.HEADERS_NAVEGADOR, Referer="https://www.itftennis.com/")

_RE_TORNEO_FEM = re.compile(r"\bw\s?\d{2,3}\b|women")
_ESTADOS_TERMINADOS = ("complet", "final", "walkover", "retired", "cancel", "abandon", "postpon")


def obtener_mismatches_itf():
    """
    Partidos del circuito ITF femenino (W15 a W100) de hoy con asimetría de ranking
    (incluye Wild Cards sin ranking). Simétrico: la favorita puede ser la local o la visita.
    """
    if motor_mismatches is None:
        return []

    hoy = U.fecha_arg()
    url = f"https://www.itftennis.com/api/v1/tournaments/order-of-play?date={hoy}&circuit=WTT"
    data = U.get_json(url, "itf", headers=HEADERS_ITF, timeout=10)
    if not isinstance(data, dict):
        return []

    resultados = []
    for m in data.get("matches", []) or []:
        if not isinstance(m, dict):
            continue

        nombre_torneo = m.get("tournamentName") or "ITF Women"
        es_fem = m.get("isWomen") is True or bool(_RE_TORNEO_FEM.search(nombre_torneo.lower()))
        if not es_fem:
            continue

        estado = str(m.get("status") or m.get("matchStatus") or "").lower()
        if any(k in estado for k in _ESTADOS_TERMINADOS):
            continue

        p1 = m.get("player1") or {}
        p2 = m.get("player2") or {}
        hay, detalle, favorito = motor_mismatches.evaluar_mismatch_tenis(
            p1.get("name", ""), p2.get("name", ""),
            p1.get("rank"), p2.get("rank"),
            entry_local=p1.get("entryStatus"), entry_visita=p2.get("entryStatus"),
        )
        if not hay:
            continue

        resultados.append({
            "id": f"itf_{m.get('id')}",
            "torneo": nombre_torneo,
            "local": p1.get("name") or "Jugadora 1",
            "visita": p2.get("name") or "Jugadora 2",
            "horario": m.get("scheduledTime") or "A confirmar",
            "detalle": f"ITF Draw Oficial — {detalle}",
            "favorito": favorito,
        })

    return resultados
