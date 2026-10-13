"""Candidatos experimentales T20/ODI: resultados oficiales, nunca runs como goles."""
import time
from datetime import datetime, timezone

import fuente_cricsheet as C
import utilidades as U


def evaluar(evento, registros, ahora=None):
    ahora = time.time() if ahora is None else ahora
    vacio = {"alertar": False, "evidencia": [], "fuentes": [], "motivo": "historial insuficiente o incompatible"}
    formato = evento.get("formato_cricket")
    if formato not in ("T20", "ODI"):
        return vacio
    if evento.get("tipo_equipo_cricket") == "club" and not evento.get("temporada_cricket"):
        return dict(vacio, motivo="calendario de clubes sin temporada explícita verificable")
    a, b = (C.identidad(evento[l]["nombre"]) for l in ("local", "visita"))
    limite = min(ahora, evento.get("startTimestamp", ahora))
    rows, vistos = [], set()
    for p in registros or []:
        if p.get("formato") != formato or p.get("id") in vistos or p.get("tipo_equipo") != evento.get("tipo_equipo_cricket"):
            continue
        try:
            ts = datetime.strptime(p["fecha"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()+86400
        except (KeyError, ValueError, TypeError):
            continue
        if not 0 <= limite-ts <= 90*86400:
            continue
        # Clubes: misma competición explícita; selecciones: mismo formato/categoría.
        if p["tipo_equipo"] == "club" and U.normalizar(p.get("competicion", "")) != U.normalizar(evento["torneo"]):
            continue
        if p["tipo_equipo"] == "club" and p.get("temporada") != str(evento.get("temporada_cricket")):
            continue
        if p.get("ganadora") not in p.get("equipos", []):
            continue
        vistos.add(p["id"])
        rows.append(p)
    rows.sort(key=lambda p: p["fecha"], reverse=True)
    for fav, rival, lado in ((a, b, "Local"), (b, a, "Visitante")):
        hf, hr = ([p for p in rows if equipo in p["equipos"]][:6] for equipo in (fav, rival))
        if min(len(hf), len(hr)) < 5:
            continue
        wf, wr = sum(p["ganadora"] == fav for p in hf), sum(p["ganadora"] == rival for p in hr)
        fuertes = sum(p["ganadora"] == fav and ((p["unidad"] == "runs" and p["margen"] >= (40 if formato == "T20" else 80))
                     or (p["unidad"] == "wickets" and p["margen"] >= 7)) for p in hf)
        h2h = [p for p in rows if set(p["equipos"]) == {fav, rival}][:3]
        domina = len(h2h) >= 2 and all(p["ganadora"] == fav for p in h2h)
        if wf/len(hf) < .8 or wr/len(hr) > .2 or fuertes < 2 or not domina:
            continue
        nombre = evento["local" if lado == "Local" else "visita"]["nombre"]
        return {"alertar": True, "favorito": lado, "fuentes": ["cricsheet"],
                "evidencia": [f"{formato}: {nombre} ganó {wf}/{len(hf)}; rival {wr}/{len(hr)} en los últimos 90 días",
                              f"{fuertes} victorias amplias: ≥{'40' if formato == 'T20' else '80'} carreras o ≥7 wickets",
                              f"Ganó los {len(h2h)} cruces directos recientes disponibles",
                              "Muestra parcial; forma, márgenes y H2H pueden compartir partidos. Umbrales experimentales."],
                "motivo": "candidato por resultados, sin calibración predictiva"}
    return vacio
