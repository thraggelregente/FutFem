"""
motor_mismatches.py
Cerebro cuantitativo del Radar Femenino (simétrico: el favorito puede ser local o visitante).
Jerarquía de Análisis:
- Nivel 1: Forma actual de la temporada vigente (partidos recientes de los últimos 35 días dominan).
- Nivel 2: Contexto reciente / H2H de los últimos 12 meses.
- Nivel 3: Descarte de partidos lejanos (> 90 días para forma, > 36 meses para H2H).
"""

import os
from datetime import datetime, timezone

import utilidades as U

LOCAL = "Local"
VISITA = "Visitante"
EMPATE = "Empate"

PUNTAJE_MINIMO = 4
PUNTAJE_ALTA = 6
PUNTAJE_MUY_ALTA = 8
MIN_PARTIDOS_TABLA = 5
VIDA_MEDIA_FORMA_DIAS = 35.0

VENTAJA_LOCAL_PUNTOS = {
    "Soccer": 0.30, "Ice Hockey": 0.20, "Basketball": 3.0, "Handball": 1.5, "Volleyball": 0.25, "Rugby": 2.0,
}
UMBRAL_BAJAS = {"Basketball": 3, "Ice Hockey": 3, "Soccer": 3, "Handball": 3, "Volleyball": 2, "Rugby": 4}

TOPE_DIFERENCIA = {
    "Soccer": 4, "Ice Hockey": 4, "Field Hockey": 4, "Futsal": 6,
    "Handball": 15, "Basketball": 30, "Rugby": 30,
    "Softball": 8, "Lacrosse": 10,
}


def _otro(lado):
    return VISITA if lado == LOCAL else LOCAL


def _pertenece(p, id_equipo):
    return id_equipo is not None and str(id_equipo) in {str(p.get("id_local")), str(p.get("id_visita"))}


def historial_valido(partidos, id_equipo, max_dias=90):
    salida = []
    vistos = set()
    for p in partidos or []:
        if not _pertenece(p, id_equipo):
            continue
        try:
            fecha = datetime.fromisoformat(str(p.get("fecha", "")).replace("Z", "+00:00"))
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone.utc)
            edad = (datetime.now(timezone.utc) - fecha).total_seconds() / 86400
            if not 0 <= edad <= max_dias or p.get("puntos_local") is None or p.get("puntos_visita") is None:
                continue
            clave = (fecha.isoformat(), str(p.get("id_local")), str(p.get("id_visita")))
            if clave not in vistos:
                vistos.add(clave)
                salida.append(p)
        except (ValueError, TypeError):
            continue
    return sorted(salida, key=lambda p: p["fecha"], reverse=True)


def calcular_dias_atras(fecha_str):
    try:
        f = datetime.fromisoformat(str(fecha_str).replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - f).days)
    except Exception:
        return 999


def obtener_umbral_deporte(deporte):
    umbrales = {
        "Soccer": 2.0, "Futsal": 3.0, "Ice Hockey": 2.5, "Floorball": 3.5,
        "Waterpolo": 4.0, "Field Hockey": 2.5,
        "Volleyball": 3.0, "Table Tennis": 3.0, "Badminton": 2.5,
        "Handball": 8.0, "Basketball": 20.0, "Rugby": 20.0,
        "Softball": 4.0, "Lacrosse": 5.0,
        "Cricket": None,
    }
    return umbrales.get(deporte, 5.0)


def _partidos_tabla(fila):
    return fila.get("victorias", 0) + fila.get("empates", 0) + fila.get("derrotas", 0)


def _tasa_victorias(fila):
    pj = _partidos_tabla(fila)
    if pj <= 0:
        return None
    return (fila.get("victorias", 0) + 0.5 * fila.get("empates", 0)) / pj


def _evaluar_tabla_lado(tabla, id_fav, id_rival, n_equipos):
    tf, tr = tabla[id_fav], tabla[id_rival]
    rf, rr = _tasa_victorias(tf), _tasa_victorias(tr)
    if rf is None or rr is None:
        return None
    if _partidos_tabla(tf) < MIN_PARTIDOS_TABLA or _partidos_tabla(tr) < MIN_PARTIDOS_TABLA:
        return None
    brecha = tr.get("posicion", 0) - tf.get("posicion", 0)
    if rf >= 0.65 and rr <= 0.30 and brecha >= max(4, round(n_equipos * 0.4)):
        return {
            "brecha": brecha,
            "detalle": (
                f"Tabla: top {tf['posicion']}° ({round(rf * 100)}% efectividad, "
                f"dif {tf.get('dif_neta', 0):+}) vs zona baja {tr['posicion']}° "
                f"({round(rr * 100)}%, dif {tr.get('dif_neta', 0):+})"
            ),
        }
    return None


def evaluar_tabla_posiciones(tabla_data, id_local, id_visita, n_equipos=None):
    if not tabla_data or id_local not in tabla_data or id_visita not in tabla_data:
        return None
    n = n_equipos or len(tabla_data)
    for lado, id_f, id_r in ((LOCAL, id_local, id_visita), (VISITA, id_visita, id_local)):
        res = _evaluar_tabla_lado(tabla_data, id_f, id_r, n)
        if res:
            return {"es_mismatch_tabla": True, "favorito": lado,
                    "detalle": res["detalle"], "delta_posiciones": res["brecha"]}
    return {"es_mismatch_tabla": False, "favorito": None, "detalle": "", "delta_posiciones": 0}


def evaluar_rendimiento_reciente(partidos, id_equipo, deporte=None):
    vacio = {"dif_prom": 0.0, "victorias": 0, "derrotas": 0, "muestras": 0,
             "dias_ultimo": None, "dias_mas_antiguo": None}
    if not partidos:
        return vacio

    tope = TOPE_DIFERENCIA.get(deporte)
    suma_pesada, suma_pesos, victorias, derrotas, muestras = 0.0, 0.0, 0, 0, 0
    edades = []
    for p in historial_valido(partidos, id_equipo)[:6]:
        dias = calcular_dias_atras(p.get("fecha", ""))
        if dias > 90:
            continue
        es_local_hist = str(p.get("id_local")) == str(id_equipo)
        pts_prop = p.get("puntos_local") if es_local_hist else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local_hist else p.get("puntos_local")
        if pts_prop is None or pts_riv is None:
            continue
        dif = pts_prop - pts_riv
        if tope is not None:
            dif = max(-tope, min(tope, dif))
        peso = 0.5 ** (dias / VIDA_MEDIA_FORMA_DIAS)
        hfa = VENTAJA_LOCAL_PUNTOS.get(deporte, 0.0)
        dif_ajustada = dif - hfa if es_local_hist else dif + hfa
        suma_pesada += dif_ajustada * peso
        suma_pesos += peso
        muestras += 1
        edades.append(dias)
        if dif > 0:
            victorias += 1
        elif dif < 0:
            derrotas += 1

    if not muestras:
        return vacio
    return {
        "dif_prom": round(suma_pesada / suma_pesos, 2),
        "victorias": victorias, "derrotas": derrotas, "muestras": muestras,
        "dias_ultimo": min(edades), "dias_mas_antiguo": max(edades),
    }


def _clave_rival(rival_id, rival_nombre):
    if rival_nombre:
        return "n:" + U.firma_equipo(rival_nombre)
    return f"i:{rival_id}" if rival_id else None


def _triangular_direccional(partidos_a, id_a, partidos_b, id_b):
    historial_a = {}
    for p in historial_valido(partidos_a, id_a)[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local = str(p.get("id_local")) == str(id_a)
        rival_id = p.get("id_visita") if es_local else p.get("id_local")
        rival_nom = p.get("nom_visita") if es_local else p.get("nom_local")
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")
        clave_rival = _clave_rival(rival_id, rival_nom)
        if clave_rival and rival_id != id_b and pts_prop is not None and pts_riv is not None:
            historial_a.setdefault(clave_rival, {
                "nombre": rival_nom, "gano": pts_prop > pts_riv, "dif": pts_prop - pts_riv
            })

    resultado = []
    vistos = set()
    for p in historial_valido(partidos_b, id_b)[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local = str(p.get("id_local")) == str(id_b)
        rival_id = p.get("id_visita") if es_local else p.get("id_local")
        rival_nom_b = p.get("nom_visita") if es_local else p.get("nom_local")
        rival_clave = _clave_rival(rival_id, rival_nom_b)
        if rival_clave not in historial_a or rival_clave in vistos:
            continue
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")
        if pts_prop is None or pts_riv is None:
            continue
        dif_b = pts_prop - pts_riv
        dato_a = historial_a[rival_clave]
        if dato_a["gano"] and dif_b < 0:
            vistos.add(rival_clave)
            resultado.append({
                "rival": dato_a["nombre"], "dif_a": dato_a["dif"],
                "dif_b": dif_b, "brecha": dato_a["dif"] - dif_b,
            })
    return resultado


def triangular_rivales(partidos_local, id_local, partidos_visita, id_visita):
    return {
        "local": _triangular_direccional(partidos_local, id_local, partidos_visita, id_visita),
        "visita": _triangular_direccional(partidos_visita, id_visita, partidos_local, id_local),
    }


def analizar_h2h_extendido(historial_h2h, id_local, id_visita):
    h2h_reciente = []
    h2h_medio = []
    h2h_viejo = []

    for p in historial_valido(historial_h2h, id_local, max_dias=365 * 3):
        if not _pertenece(p, id_visita):
            continue
        dias = calcular_dias_atras(p.get("fecha", ""))
        if dias > 365 * 3:
            continue
        pts_loc = p.get("puntos_local")
        pts_vis = p.get("puntos_visita")
        if pts_loc is None or pts_vis is None:
            continue
        es_local_hist = str(p.get("id_local")) == str(id_local)
        pts_nuestro_local = pts_loc if es_local_hist else pts_vis
        pts_nuestro_visita = pts_vis if es_local_hist else pts_loc
        if pts_nuestro_local > pts_nuestro_visita:
            ganador = LOCAL
        elif pts_nuestro_local < pts_nuestro_visita:
            ganador = VISITA
        else:
            ganador = EMPATE
        entrada = {"ganador": ganador, "dif": abs(pts_loc - pts_vis)}
        if dias <= 180:
            h2h_reciente.append(entrada)
        elif dias <= 540:
            h2h_medio.append(entrada)
        else:
            h2h_viejo.append(entrada)

    return {
        "reciente": h2h_reciente,
        "medio": h2h_medio,
        "viejo": h2h_viejo,
    }


def _rank_valido(rank):
    try:
        r = int(rank)
        return r if r > 0 else None
    except (TypeError, ValueError):
        return None


def _es_wc(nombre, entry=None):
    n = (nombre or "").lower()
    return (entry or "").upper() in ("WC", "WILD CARD") or "(wc)" in n or "[wc]" in n


def evaluar_mismatch_tenis(nombre_local, nombre_visita, rank_local, rank_visita,
                           entry_local=None, entry_visita=None,
                           fuera_local=False, fuera_visita=False, corte_ranking=None):
    rl, rv = _rank_valido(rank_local), _rank_valido(rank_visita)

    # Ranking desconocido no equivale a estar fuera de un top truncado.
    for lado, nom_f, rk_f, nom_r, rk_r in (
        (LOCAL, nombre_local, rl, nombre_visita, rv),
        (VISITA, nombre_visita, rv, nombre_local, rl),
    ):
        if rk_f is None or rk_r is None or rk_r <= rk_f:
            continue
        ratio, brecha = rk_r / rk_f, rk_r - rk_f
        if rk_f <= 50 and ratio >= 5 and brecha >= 100:
            puntos, nivel = 3, "Fuerte"
        elif rk_f <= 100 and ratio >= 3 and brecha >= 60:
            puntos, nivel = 2, "Moderada"
        elif rk_f <= 400 and ratio >= 3 and brecha >= 200:
            puntos, nivel = 2, "Moderada"
        else:
            continue
        detalle = f"Brecha de ranking {nivel.lower()}: {nom_f} #{rk_f} vs {nom_r} #{rk_r}; requiere contexto deportivo"
        return True, detalle, lado, puntos

    return False, "", None, 0


def ajustar_tenis_por_contexto(favorito_lado, ctx):
    if not ctx or not ctx.get("disponible"):
        return 0, []
    return max(-2, min(2, int(ctx.get("favorita_ventaja", 0)))), list(ctx.get("detalles", []))


def evaluar_descanso(partidos_a, id_a, partidos_b, id_b):
    def _dias_ultimo_partido(partidos):
        for p in (partidos or [])[:3]:
            dias = calcular_dias_atras(p.get("fecha", ""))
            if dias < 90:
                return dias
        return None

    dias_a = _dias_ultimo_partido(historial_valido(partidos_a, id_a))
    dias_b = _dias_ultimo_partido(historial_valido(partidos_b, id_b))
    if dias_a is None or dias_b is None:
        return None

    if dias_b <= 3 and 4 <= dias_a - dias_b and dias_a <= 21:
        return {"favorito": LOCAL, "dias_a": dias_a, "dias_b": dias_b,
                "detalle": f"Descanso: local descansó {dias_a}d vs visita {dias_b}d"}
    if dias_a <= 3 and 4 <= dias_b - dias_a and dias_b <= 21:
        return {"favorito": VISITA, "dias_a": dias_a, "dias_b": dias_b,
                "detalle": f"Descanso: visita descansó {dias_b}d vs local {dias_a}d"}
    return None


def _partidos_en_dias(partidos, dias):
    return sum(1 for p in (partidos or [])[:8] if calcular_dias_atras(p.get("fecha", "")) <= dias)


def evaluar_congestion(partidos_a, id_a, partidos_b, id_b, dias=7, minimo_historial=4):
    partidos_a = historial_valido(partidos_a, id_a)
    partidos_b = historial_valido(partidos_b, id_b)
    if len(partidos_a or []) < minimo_historial or len(partidos_b or []) < minimo_historial:
        return None
    n_a, n_b = _partidos_en_dias(partidos_a, dias), _partidos_en_dias(partidos_b, dias)
    if n_b >= 3 and n_a <= 1:
        return {"favorito": LOCAL, "n_a": n_a, "n_b": n_b,
                "detalle": f"Calendario: visita jugó {n_b} partidos en {dias} días vs {n_a} del local"}
    if n_a >= 3 and n_b <= 1:
        return {"favorito": VISITA, "n_a": n_a, "n_b": n_b,
                "detalle": f"Calendario: local jugó {n_a} partidos en {dias} días vs {n_b} de la visita"}
    return None


def evaluar_momentum(partidos, id_equipo):
    racha = 0
    for p in historial_valido(partidos, id_equipo)[:6]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local = str(p.get("id_local")) == str(id_equipo)
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")
        if pts_prop is None or pts_riv is None:
            break
        if pts_prop > pts_riv:
            racha += 1
        else:
            break
    return racha


def evaluar_elo(elo):
    if not elo:
        return None
    p_local = elo["p_local"]
    p = max(p_local, 1.0 - p_local)
    if p >= 0.88:
        puntos = 3
    elif p >= 0.80:
        puntos = 2
    elif p >= 0.72:
        puntos = 1
    else:
        return None
    favorito = LOCAL if p_local >= 0.5 else VISITA
    elo_f, elo_r = (elo["elo_local"], elo["elo_visita"]) if favorito == LOCAL else (elo["elo_visita"], elo["elo_local"])
    return {
        "favorito": favorito, "puntos": puntos,
        "detalle": (f"Elo: {favorito} {elo_f} vs {elo_r} (ajuste de localía; "
                    f"{elo['n_local']}/{elo['n_visita']} partidos en el libro)"),
    }


def evaluar_plantel(bajas_local, bajas_visita, deporte):
    if not bajas_local or not bajas_visita or bajas_local.get("inferido") or bajas_visita.get("inferido"):
        return None
    umbral = UMBRAL_BAJAS.get(deporte, 3)
    fl, fv = int(bajas_local.get("fuera", 0)), int(bajas_visita.get("fuera", 0))
    for fav, sano, golpeado in ((LOCAL, fl, fv), (VISITA, fv, fl)):
        if golpeado >= umbral and sano <= 1:
            rival = _otro(fav)
            return {
                "favorito": fav, "puntos": 2 if golpeado >= umbral + 2 else 1,
                "detalle": f"Plantel: {rival} con {golpeado} bajas confirmadas vs {sano} de {fav}",
            }
    return None


def sugerir_mercado(deporte, favorito, nombre_fav=None):
    return None


def evaluar_mismatch(deporte, perf_local, perf_visita, triangulaciones, h2h,
                     tabla_local_visita=None, datos_extra=None):
    puntos = {LOCAL: 0, VISITA: 0}
    textos = {LOCAL: [], VISITA: []}
    grupos = {LOCAL: set(), VISITA: set()}
    fuerza = {LOCAL: False, VISITA: False}
    puntos_grupo = {LOCAL: {}, VISITA: {}}
    limites_grupo = {"historial": 4, "tabla": 2, "calendario": 1, "plantel": 2}

    def sumar(lado, pts, texto, grupo="historial"):
        anterior = puntos_grupo[lado].get(grupo, 0)
        nuevo = min(limites_grupo.get(grupo, 4), anterior + pts)
        puntos[lado] += nuevo - anterior
        puntos_grupo[lado][grupo] = nuevo
        textos[lado].append(texto)
        grupos[lado].add(grupo)

    if tabla_local_visita and tabla_local_visita.get("es_mismatch_tabla"):
        fuerza[tabla_local_visita["favorito"]] = True
        sumar(tabla_local_visita["favorito"], 2, tabla_local_visita["detalle"], "tabla")

    forma_sumo = {LOCAL: False, VISITA: False}
    umbral = obtener_umbral_deporte(deporte)
    if umbral is not None:
        perf = {LOCAL: perf_local, VISITA: perf_visita}
        for fav in (LOCAL, VISITA):
            pf, pr = perf[fav], perf[_otro(fav)]
            if pf["muestras"] >= 4 and pr["muestras"] >= 4 and pf["victorias"] >= 3 and pr["derrotas"] >= 3:
                brecha = pf["dif_prom"] - pr["dif_prom"]
                hfa_partido = VENTAJA_LOCAL_PUNTOS.get(deporte, 0.0)
                brecha += hfa_partido if fav == LOCAL else -hfa_partido
                if brecha >= umbral:
                    extra = 1 if brecha >= umbral * 2 else 0
                    forma_sumo[fav] = True
                    fuerza[fav] = True
                    sumar(fav, 2 + extra, (
                        f"Forma: {fav} {pf['dif_prom']:+} por partido "
                        f"({pf['victorias']}V en {pf['muestras']}) vs rival "
                        f"{pr['dif_prom']:+} ({pr['derrotas']}D en {pr['muestras']})"
                    ))

    for clave, fav in (("local", LOCAL), ("visita", VISITA)):
        lista = (triangulaciones or {}).get(clave) or []
        if lista:
            mejor = max(lista, key=lambda x: x["brecha"])
            pts = 1 if len(lista) == 1 else (2 if len(lista) == 2 else 3)
            sumar(fav, pts, (
                f"Triangulación vs {mejor['rival']}: ganó por {mejor['dif_a']:+} "
                f"y el rival cayó por {mejor['dif_b']:+} "
                f"({len(lista)} rival/es en común)"
            ))

    if h2h:
        for fav in (LOCAL, VISITA):
            recientes = [x for x in h2h.get("reciente", []) if x["ganador"] == fav]
            medios = [x for x in h2h.get("medio", []) if x["ganador"] == fav]
            viejos = [x for x in h2h.get("viejo", []) if x["ganador"] == fav]
            total_fav = len(recientes) + len(medios) + len(viejos)
            total_rival = sum(1 for k in ("reciente", "medio", "viejo")
                              for x in h2h.get(k, []) if x["ganador"] == _otro(fav))
            if len(recientes) >= 2 and total_fav / max(1, total_fav + total_rival) >= 0.75:
                pts = 2 if recientes else (1 if medios else 0.5)
                detalle = f"H2H: {fav} ganó {total_fav} cruces ("
                partes = []
                if recientes: partes.append(f"{len(recientes)} recientes")
                if medios: partes.append(f"{len(medios)} 6-18m")
                if viejos: partes.append(f"{len(viejos)} +18m")
                detalle += ", ".join(partes) + ")"
                if total_rival:
                    detalle += f" vs {total_rival} del rival"
                sumar(fav, pts, detalle, "historial")

    if datos_extra and datos_extra.get("descanso"):
        d = datos_extra["descanso"]
        sumar(d["favorito"], 1, d["detalle"], "calendario")

    if datos_extra and datos_extra.get("congestion"):
        c = datos_extra["congestion"]
        d = datos_extra.get("descanso")
        if not (d and d.get("favorito") == c["favorito"]):
            sumar(c["favorito"], 1, c["detalle"], "calendario")

    if datos_extra and datos_extra.get("elo"):
        e = datos_extra["elo"]
        fuerza[e["favorito"]] = True
        sumar(e["favorito"], e["puntos"], e["detalle"], "historial")

    if datos_extra and datos_extra.get("plantel"):
        pl_ = datos_extra["plantel"]
        sumar(pl_["favorito"], pl_["puntos"], pl_["detalle"], "plantel")

    if datos_extra:
        racha_loc = datos_extra.get("racha_local", 0)
        racha_vis = datos_extra.get("racha_visita", 0)
        if racha_loc >= 4 and not forma_sumo[LOCAL]:
            sumar(LOCAL, 2 if racha_loc >= 6 else 1, f"Momentum: {LOCAL} {racha_loc} victorias seguidas")
        if racha_vis >= 4 and not forma_sumo[VISITA]:
            sumar(VISITA, 2 if racha_vis >= 6 else 1, f"Momentum: {VISITA} {racha_vis} victorias seguidas")

    favorito = LOCAL if puntos[LOCAL] >= puntos[VISITA] else VISITA
    contrario = _otro(favorito)
    puntaje, puntaje_contra = puntos[favorito], puntos[contrario]

    resultado = {
        "hay_mismatch": False, "favorito": None,
        "puntaje": puntaje, "puntaje_contrario": puntaje_contra,
        "alertas": [], "confianza": "", "motivo_descarte": "",
    }

    if puntaje == 0:
        resultado["motivo_descarte"] = "sin señales"
    elif not fuerza[favorito]:
        resultado["motivo_descarte"] = "sin evidencia de diferencia de nivel"
    elif puntos_grupo[contrario].get("historial", 0) >= 2 or puntos_grupo[contrario].get("tabla", 0) >= 2 or puntaje - puntaje_contra < 2:
        resultado["motivo_descarte"] = f"señales contradictorias ({puntaje} vs {puntaje_contra})"
    elif puntaje < PUNTAJE_MINIMO:
        resultado["motivo_descarte"] = f"puntaje insuficiente ({puntaje}/{PUNTAJE_MINIMO})"
    else:
        if puntaje >= PUNTAJE_MUY_ALTA:
            confianza = "Muy Alta"
        elif puntaje >= PUNTAJE_ALTA:
            confianza = "Alta"
        else:
            confianza = "Media"
        n_grupos = len(grupos[favorito])
        muestras = min(perf_local.get("muestras", 0), perf_visita.get("muestras", 0))
        reciente = all(p.get("dias_ultimo") is not None and p["dias_ultimo"] <= 21
                       and p.get("dias_mas_antiguo") is not None and p["dias_mas_antiguo"] <= 60
                       for p in (perf_local, perf_visita))
        calidad = "Suficiente" if muestras >= 4 and reciente else "Limitada"
        if n_grupos < 2:
            confianza = "Media"
        elif n_grupos < 3 and confianza == "Muy Alta":
            confianza = "Alta"
        resultado.update({
            "hay_mismatch": True,
            "favorito": favorito,
            "alertas": textos[favorito],
            "confianza": confianza,
            "grupos_independientes": len(grupos[favorito]),  # compatibilidad, son familias de señales
            "calidad_datos": calidad,
            "magnitud": "Fuerte" if puntaje >= 6 else "Moderada",
            "familias_senales": sorted(grupos[favorito]),
        })
    return resultado
