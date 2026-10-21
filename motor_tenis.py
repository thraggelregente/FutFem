"""Asimetrías de tenis femenino: ranking, experiencia y contexto verificable.

WC describe una vía de ingreso, nunca una prueba de debilidad. Sin cobertura
del historial, cero observaciones significa desconocido, no jugadora amateur.
"""
import time

import motor_mismatches as M
import analisis_deportivo as A
import utilidades as U


def _recientes_verificados(perfil, ahora):
    salida = {}
    for p in (perfil or {}).get('partidos', []):
        ts = p.get('ts')
        if not isinstance(ts,(int,float)) or type(p.get('gano')) is not bool:
            continue
        # La semana no acredita que el partido ya acabó durante esa misma semana.
        disponible = ts + (7*86400 if p.get('fecha_precision') == 'semana del torneo' else 0)
        if not ahora-120*86400 <= ts < ahora or disponible >= ahora:
            continue
        if p.get('estado_resultado') not in (None, 'normal'):
            continue
        rival = U.normalizar(p.get('rival') or '')
        if rival:
            salida.setdefault((ts,rival,str(p.get('torneo')),str(p.get('round'))),p)
    return sorted(salida.values(), key=lambda p:p['ts'], reverse=True)


def _cruces(pf, pr, nombre_f, nombre_r, ahora):
    a, b = _recientes_verificados(pf,ahora), _recientes_verificados(pr,ahora)
    nf, nr = U.normalizar(nombre_f), U.normalizar(nombre_r)
    directos = {}
    conflicto = False
    # Una sola perspectiva para contar cruces: las fechas de dos proveedores
    # pueden ser exactas o semana de torneo y no acreditan dos partidos distintos.
    propios=[p for p in a if U.normalizar(p['rival']) == nr]
    perspectivas=((propios,nr,False),) if propios else ((b,nf,True),)
    for rows, rival, invertido in perspectivas:
        for p in rows:
            if U.normalizar(p['rival']) != rival:
                continue
            key=(p['ts'],str(p.get('torneo')),str(p.get('round')))
            gano = not p['gano'] if invertido else p['gano']
            if key in directos and directos[key] != gano:
                conflicto = True
            directos[key] = gano
    latest=[]
    for rows in (a,b):
        index={}
        for p in rows:
            key=U.normalizar(p['rival'])
            if key not in (nf,nr):index.setdefault(key,p['gano'])
        latest.append(index)
    shared=set(latest[0]) & set(latest[1])
    comunes={'favor':sum(latest[0][k] and not latest[1][k] for k in shared),
             'contra':sum(latest[1][k] and not latest[0][k] for k in shared),'total':len(shared)}
    h2h={'favor':sum(directos.values()),'contra':sum(not v for v in directos.values()),'conflicto':conflicto}
    return h2h, comunes


def _banda(rank):
    if not isinstance(rank, int) or rank <= 0:
        return None
    return 0 if rank <= 100 else 1 if rank <= 300 else 2 if rank <= 700 else 3


def _comparar(perfil_f, perfil_r, superficie=None, ahora=None):
    """Compara victorias solo en bandas de rivales que ambos han enfrentado."""
    ahora = time.time() if ahora is None else ahora
    listas = []
    for perfil in (perfil_f, perfil_r):
        lista = [p for p in (perfil or {}).get("partidos", [])
                 if ahora - (365 if superficie else 120) * 86400 <= p["ts"] <= ahora
                 and p['ts'] + (7*86400 if p.get('fecha_precision') == 'semana del torneo' else 0) < ahora
                 and type(p.get('gano')) is bool and p.get('estado_resultado') in (None,'normal')
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
    complemento=(perfil or {}).get("complemento_tennis_api") or {}
    if complemento.get("muestras_2anios",0)>5:
        return False # El historial ITF observado contradice la condición de poca experiencia.
    mejor = (perfil or {}).get("mejor_ranking")
    return bool(perfil and perfil.get("cobertura_completa_2anios") and exp is not None and exp <= 5
                and perfil.get("muestras_2anios", 0) <= 3
                and not (isinstance(mejor, (int, float)) and 0 < mejor <= 100))


def evaluar(ev, perfiles=None, ahora=None):
    ahora = time.time() if ahora is None else ahora
    modalidad = U.normalizar(str(ev.get('torneo',''))+' '+str(ev.get('modalidad','')))
    if any(x in modalidad.split() for x in ('doubles','dobles','srl','simulated')):
        return {'alertar':False,'motivo':'modalidad no compatible con individuales reales','puntaje':0}
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
        prefix = "Historial oficial registrado" if all((p or {}).get("fuente", "WTA historial oficial")=="WTA historial oficial" for p in (pf,pr)) else "Historial registrado en las fuentes consultadas"
        evidencia.append(f"{prefix} en los últimos dos años: {jug_f.get('nombre')} "
                         f"{pf.get('muestras_2anios', 0)} partidos; {jug_r.get('nombre')} {pr.get('muestras_2anios', 0)} partidos. "
                         "No equivale necesariamente a toda su carrera. Las fechas identifican la semana del torneo, no el día de cada partido.")
    for nombre,perfil in ((jug_f.get('nombre'),pf),(jug_r.get('nombre'),pr)):
        complemento=(perfil or {}).get('complemento_tennis_api')
        if complemento:
            evidencia.append(f"Tennis API: {nombre}, {complemento.get('muestras_2anios',0)} resultados WTA/ITF registrados; "
                             f"{len(complemento.get('recientes',[]))} recientes mostrados. Cobertura parcial, contexto sin puntaje adicional.")
        elif perfil and perfil.get('fuente')=='Tennis API historial WTA/ITF':
            evidencia.append(f"{nombre}: contexto Tennis API WTA/ITF; no demuestra carrera completa ni condición amateur.")
    forma = _comparar(pf, pr, ahora=ahora)
    superficie = _comparar(pf, pr, ev.get("superficie"), ahora=ahora) if ev.get("superficie") else None
    h2h, comunes = _cruces(pf, pr, jug_f.get('nombre',''), jug_r.get('nombre',''), ahora)
    faltantes = []
    if forma is None:
        faltantes.append('Forma comparable: faltan al menos cuatro resultados por jugadora frente a una misma banda de ranking rival.')
    if not ev.get('superficie'):
        faltantes.append('Superficie del partido sin confirmar en las fuentes consultadas.')
    elif superficie is None:
        faltantes.append('Superficie: no hay una muestra comparable de al menos ocho partidos por jugadora.')
    if h2h['favor']+h2h['contra']:
        evidencia.append(f"H2H en los últimos 120 días: {jug_f.get('nombre')} {h2h['favor']} victorias; {jug_r.get('nombre')} {h2h['contra']}. Solo cruces verificables, sin duplicar observaciones.")
    else:
        faltantes.append('H2H reciente: no se encontraron cruces verificables en los últimos 120 días.')
    if comunes['total']:
        evidencia.append(f"Rivales comunes en 120 días: {comunes['total']}; {comunes['favor']} comparaciones favorables a {jug_f.get('nombre')} y {comunes['contra']} a {jug_r.get('nombre')}. Se usa el último resultado frente a cada rival; no equivalen a rivales del mismo nivel actual.")
    else:
        faltantes.append('Rivales comunes: no hay resultados compartidos verificables en los últimos 120 días.')
    apoyo = 0
    contradiccion = False
    for nombre, res in (("Forma frente a bandas comparables de rivales", forma), ("Superficie oficial " + str(ev.get("superficie")), superficie)):
        if res is None:
            continue
        evidencia.append(f"{nombre}: diferencia de tasa de victorias {res['brecha']:+.0%} "
                         f"({jug_f.get('nombre')} menos {jug_r.get('nombre')}); "
                         f"muestras: {jug_f.get('nombre')} {res['n_f']} partidos, {jug_r.get('nombre')} {res['n_r']} partidos.")
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
    resultado = {"alertar": puntos >= 2, "favorito": fav, "puntaje": puntos, "evidencia": evidencia,
            "tipo": "ASIMETRÍA TENIS FEMENINO" if asimetria else "CANDIDATO TENIS FEMENINO — BRECHA DE RANKING",
            "calidad": "Documentada, con límites de cobertura" if asimetria else "Limitada",
            "fuentes": sorted({p.get("fuente", "historial sin atribución") for p in (pf,pr) if p} |
                              {"Tennis API historial WTA/ITF" for p in (pf,pr) if p and p.get("complemento_tennis_api")})}
    analisis = A.tenis(resultado, forma, superficie, h2h, comunes, faltantes)
    if h2h['conflicto'] or (h2h['contra'] >= 2 and h2h['favor'] == 0) or comunes['contra'] >= 2:
        analisis.update(estado='sin_recomendacion', selecciones=[], criterio='Los cruces o los rivales comunes aportan datos contradictorios; no se selecciona un mercado.')
    for pick in analisis['selecciones']:
        pick['seleccion'] = jug_f.get('nombre')
    resultado['analisis_deportivo'] = analisis
    return resultado
