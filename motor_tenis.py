"""Asimetrías de tenis femenino: ranking, experiencia y contexto verificable.

WC describe una vía de ingreso, nunca una prueba de debilidad. Sin cobertura
del historial, cero observaciones significa desconocido, no jugadora amateur.
"""
import time

import motor_mismatches as M


def _banda(rank):
    if not isinstance(rank, int) or rank <= 0:
        return None
    return 0 if rank <= 100 else 1 if rank <= 300 else 2 if rank <= 700 else 3


def _comparar(perfil_f, perfil_r, superficie=None):
    """Compara victorias solo en bandas de rivales que ambos han enfrentado."""
    listas = []
    for perfil in (perfil_f, perfil_r):
        lista = [p for p in (perfil or {}).get("partidos", [])
                 if p["ts"] >= time.time() - (365 if superficie else 120) * 86400
                 and (not superficie or p.get("superficie", "").lower() == superficie.lower())
                 and _banda(p.get("ranking_rival")) is not None]
        listas.append(lista)
    comunes = {_banda(p["ranking_rival"]) for p in listas[0]} & {_banda(p["ranking_rival"]) for p in listas[1]}
    if not comunes:
        return None
    minimo = 8 if superficie else 4
    tasas = []
    for banda in comunes:
        a = [p for p in listas[0] if _banda(p["ranking_rival"]) == banda]
        b = [p for p in listas[1] if _banda(p["ranking_rival"]) == banda]
        if len(a) >= minimo and len(b) >= minimo:
            tasas.append((sum(p["gano"] for p in a) / len(a), sum(p["gano"] for p in b) / len(b), len(a), len(b)))
    if not tasas:
        return None
    return {"brecha": sum(a - b for a, b, _n, _m in tasas) / len(tasas),
            "n_f": sum(n for _a, _b, n, _m in tasas), "n_r": sum(m for _a, _b, _n, m in tasas)}


def _experiencia(perfil):
    if not perfil:
        return None
    carrera = perfil.get("experiencia_carrera_wta")
    if carrera is None:
        return None
    return max(carrera, perfil.get("muestras_2anios", 0))


def _novata_documentada(perfil):
    exp = _experiencia(perfil)
    mejor = (perfil or {}).get("mejor_ranking")
    return bool(perfil and perfil.get("cobertura_completa_2anios") and exp is not None and exp <= 5
                and perfil.get("muestras_2anios", 0) <= 3
                and not (isinstance(mejor, (int, float)) and 0 < mejor <= 100))


def evaluar(ev, perfiles=None):
    perfiles = perfiles or {}
    a, b = ev.get("local") or {}, ev.get("visita") or {}
    hay, detalle, fav, puntos = M.evaluar_mismatch_tenis(a.get("nombre"), b.get("nombre"), a.get("ranking"), b.get("ranking"))
    evidencia = [detalle] if hay else []
    experiencia_senal = False
    # Un debut documentado también puede importar fuera del top 400.
    if not hay:
        for lado, contrario in ((M.LOCAL, M.VISITA), (M.VISITA, M.LOCAL)):
            pf, pr = perfiles.get(lado), perfiles.get(contrario)
            rival = b if lado == M.LOCAL else a
            favorita = a if lado == M.LOCAL else b
            exp = _experiencia(pf)
            wc = rival.get("entry") == "WC" and rival.get("entry_fuente") == "WTA cuadro oficial"
            if (wc and _novata_documentada(pr) and exp is not None and exp >= 50
                    and len((pf or {}).get("recientes", [])) >= 4
                    and isinstance(favorita.get("ranking"), int) and favorita["ranking"] <= 1200):
                hay, fav, puntos, experiencia_senal = True, lado, 4, True
                evidencia = [f"Experiencia WTA registrada: favorita {exp} partidos frente a rival con {_experiencia(pr)}; "
                             "wild card confirmada y paginación del feed de dos años verificada. "
                             "Cobertura ITF limitada; no demuestra condición amateur."]
                break
    if not hay:
        return {"alertar": False, "motivo": "sin brecha verificada", "puntaje": 0}

    contrario = M.VISITA if fav == M.LOCAL else M.LOCAL
    pf, pr = perfiles.get(fav), perfiles.get(contrario)
    jug_f, jug_r = (a, b) if fav == M.LOCAL else (b, a)
    contexto = bool(pf and pr and len(pf.get("recientes", [])) >= 4 and len(pr.get("recientes", [])) >= 4)
    if jug_r.get("entry") == "WC":
        evidencia.append("Rival con wild card confirmada; el ingreso WC no suma puntos de debilidad.")
        servicio = (pr or {}).get("servicio")
        if servicio:
            evidencia.append(f"Servicio registrado de la rival: {servicio['dobles_faltas_por_partido']} dobles faltas por partido "
                             f"en {servicio['partidos']} partidos; dato descriptivo, no añade puntaje.")
    for j in (a, b):
        evidencia.append(f"Ranking {j.get('nombre')}: {j.get('ranking') or 'desconocido'}; "
                         f"{j.get('ranking_fuente') or 'sin fuente'}; fecha {j.get('ranking_fecha') or 'sin fecha'}")
    if pf and pr:
        evidencia.append(f"Historial oficial: {pf.get('muestras_2anios', 0)}/{pr.get('muestras_2anios', 0)} partidos "
                         "registrados en dos años; fechas con precisión de semana del torneo.")
    forma = _comparar(pf, pr)
    superficie = _comparar(pf, pr, ev.get("superficie")) if ev.get("superficie") else None
    apoyo = 0
    contradiccion = False
    for nombre, res in (("Forma frente a bandas comparables de rivales", forma), ("Superficie oficial " + str(ev.get("superficie")), superficie)):
        if res is None:
            continue
        evidencia.append(f"{nombre}: brecha de victorias {res['brecha']:+.0%}; muestras {res['n_f']}/{res['n_r']}")
        if res["brecha"] >= 0.25:
            apoyo += 1
        elif res["brecha"] <= -0.25:
            contradiccion = True
    # Forma y superficie se solapan; apoyo conjunto acotado.
    puntos += min(2, apoyo)
    mejor_r = (pr or {}).get("mejor_ranking")
    regreso = bool(pr and not pr.get("recientes") and isinstance(mejor_r, (int, float)) and 0 < mejor_r <= 100)
    if regreso:
        evidencia.append("Rival ex top 100 con poca actividad reciente: posible regreso, no debutante.")
        contradiccion = True
    if contradiccion:
        return {"alertar": False, "motivo": "contexto contradice la brecha de ranking", "puntaje": puntos}
    asimetria = experiencia_senal or (contexto and apoyo > 0 and puntos >= 4)
    if not contexto and not experiencia_senal:
        evidencia.append("Contexto reciente insuficiente: candidato por ranking, sin confirmar superioridad deportiva.")
    return {"alertar": puntos >= 2, "favorito": fav, "puntaje": puntos, "evidencia": evidencia,
            "tipo": "ASIMETRÍA TENIS FEMENINO" if asimetria else "CANDIDATO TENIS FEMENINO — BRECHA DE RANKING",
            "calidad": "Documentada, con límites de cobertura" if asimetria else "Limitada",
            "fuentes": ["WTA historial oficial"] if pf or pr else []}
