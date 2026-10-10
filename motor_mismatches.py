"""
motor_mismatches.py
Cerebro cuantitativo del Radar Femenino (simétrico: el favorito puede ser local o visitante).

9 señales independientes, cada una suma puntos al lado al que favorece:
  1. Tabla de la temporada vigente (efectividad + brecha de posiciones)   -> 2 pts
  2. Contraste de forma reciente (rachas + diferencial por partido)       -> 2-3 pts
  3. Triangulación de rivales en común                                    -> 1-3 pts
  4. H2H extendido (12-36 meses)                                          -> 1-3 pts
  5. Tenis: ranking + Wild Card                                           -> 1-3 pts
  6. Descanso entre partidos                                              -> 0-1 pt
  7. Bajas / lesiones                                                     -> 0-2 pts
  8. Momentum (racha de victorias)                                        -> 0-2 pts
  9. Clima / cancha neutral                                               -> 0-1 pt

Sistema de decisión:
- Alerta si: puntaje_favorito >= 4 Y puntaje_rival <= 1
- Confianza: Media (4-5) / Alta (6-7) / Muy Alta (8+)
"""

import os
from datetime import datetime, timezone

LOCAL = "Local"
VISITA = "Visitante"
EMPATE = "Empate"

PUNTAJE_MINIMO = 4
PUNTAJE_ALTA = 6
PUNTAJE_MUY_ALTA = 8
MIN_PARTIDOS_TABLA = 5


def _otro(lado):
    return VISITA if lado == LOCAL else LOCAL


def calcular_dias_atras(fecha_str):
    """Días transcurridos desde una fecha ISO (999 si no se puede interpretar)."""
    try:
        f = datetime.fromisoformat(str(fecha_str).replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - f).days)
    except Exception:
        return 999


def obtener_umbral_deporte(deporte):
    """Brecha mínima de diferencial promedio para considerar contraste de forma."""
    umbrales = {
        "Soccer": 2.0, "Futsal": 3.0, "Ice Hockey": 2.5, "Floorball": 3.5,
        "Waterpolo": 4.0, "Field Hockey": 2.5,
        "Volleyball": 3.0, "Table Tennis": 3.0, "Badminton": 2.5,
        "Handball": 8.0, "Basketball": 20.0, "Rugby": 20.0,
        "Cricket": None,
    }
    return umbrales.get(deporte, 5.0)


# ---------------------------------------------------------------------------
# SEÑAL 1: TABLA
# ---------------------------------------------------------------------------
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


def evaluar_tabla_posiciones(tabla_data, id_local, id_visita):
    if not tabla_data or id_local not in tabla_data or id_visita not in tabla_data:
        return None
    n = len(tabla_data)
    for lado, id_f, id_r in ((LOCAL, id_local, id_visita), (VISITA, id_visita, id_local)):
        res = _evaluar_tabla_lado(tabla_data, id_f, id_r, n)
        if res:
            return {"es_mismatch_tabla": True, "favorito": lado,
                    "detalle": res["detalle"], "delta_posiciones": res["brecha"]}
    return {"es_mismatch_tabla": False, "favorito": None, "detalle": "", "delta_posiciones": 0}


# ---------------------------------------------------------------------------
# SEÑAL 2: FORMA RECIENTE
# ---------------------------------------------------------------------------
def evaluar_rendimiento_reciente(partidos, id_equipo):
    """Últimos 6 partidos terminados (máximo 90 días de antigüedad)."""
    vacio = {"dif_prom": 0.0, "victorias": 0, "derrotas": 0, "muestras": 0}
    if not partidos:
        return vacio

    diferencias, victorias, derrotas = [], 0, 0
    for p in partidos[:6]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local_hist = p.get("id_local") == id_equipo
        pts_prop = p.get("puntos_local") if es_local_hist else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local_hist else p.get("puntos_local")
        if pts_prop is None or pts_riv is None:
            continue
        dif = pts_prop - pts_riv
        diferencias.append(dif)
        if dif > 0:
            victorias += 1
        elif dif < 0:
            derrotas += 1

    if not diferencias:
        return vacio
    return {
        "dif_prom": round(sum(diferencias) / len(diferencias), 2),
        "victorias": victorias, "derrotas": derrotas, "muestras": len(diferencias),
    }


# ---------------------------------------------------------------------------
# SEÑAL 3: TRIANGULACIÓN
# ---------------------------------------------------------------------------
def _triangular_direccional(partidos_a, id_a, partidos_b, id_b):
    """A le ganó a C y B perdió con ese mismo C (últimos 90 días)."""
    historial_a = {}
    for p in partidos_a[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local = p.get("id_local") == id_a
        rival_id = p.get("id_visita") if es_local else p.get("id_local")
        rival_nom = p.get("nom_visita") if es_local else p.get("nom_local")
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")
        if rival_id and rival_id != id_b and pts_prop is not None and pts_riv is not None:
            historial_a.setdefault(rival_id, {
                "nombre": rival_nom, "gano": pts_prop > pts_riv, "dif": pts_prop - pts_riv
            })

    resultado = []
    vistos = set()
    for p in partidos_b[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local = p.get("id_local") == id_b
        rival_id = p.get("id_visita") if es_local else p.get("id_local")
        if rival_id not in historial_a or rival_id in vistos:
            continue
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")
        if pts_prop is None or pts_riv is None:
            continue
        dif_b = pts_prop - pts_riv
        dato_a = historial_a[rival_id]
        if dato_a["gano"] and dif_b < 0:
            vistos.add(rival_id)
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


# ---------------------------------------------------------------------------
# SEÑAL 4: H2H EXTENDIDO (con tu mejora)
# ---------------------------------------------------------------------------
def analizar_h2h_extendido(historial_h2h, id_local, id_visita):
    """
    H2H con ventana extendida:
    - 0-6 meses: peso 2
    - 6-18 meses: peso 1
    - 18-36 meses: peso 0.5
    """
    h2h_reciente = []  # 0-6 meses
    h2h_medio = []     # 6-18 meses
    h2h_viejo = []     # 18-36 meses

    for p in historial_h2h or []:
        dias = calcular_dias_atras(p.get("fecha", ""))
        if dias > 365 * 3:
            continue
        pts_loc = p.get("puntos_local")
        pts_vis = p.get("puntos_visita")
        if pts_loc is None or pts_vis is None:
            continue
        es_local_hist = p.get("id_local") == id_local
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


# ---------------------------------------------------------------------------
# SEÑAL 5: TENIS (ranking + Wild Card)
# ---------------------------------------------------------------------------
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
                           entry_local=None, entry_visita=None):
    """
    Devuelve (hay_mismatch, detalle, favorito, puntos).
    Sistema de niveles:
    - Favorita top 30 vs WC sin ranking -> 3 pts (Rojo)
    - Favorita top 100 vs WC sin ranking -> 2 pts (Naranja)
    - Favorita top 200 vs WC sin ranking (ITF) -> 1 pt (Amarillo)
    """
    rl, rv = _rank_valido(rank_local), _rank_valido(rank_visita)
    wc_l, wc_v = _es_wc(nombre_local, entry_local), _es_wc(nombre_visita, entry_visita)

    for lado, nom_f, rk_f, nom_r, rk_r, wc_r in (
        (LOCAL, nombre_local, rl, nombre_visita, rv, wc_v),
        (VISITA, nombre_visita, rv, nombre_local, rl, wc_l),
    ):
        if rk_f is None:
            continue
        # Sistema de niveles
        puntos = 0
        if rk_f <= 30 and (rk_r is None and wc_r or (rk_r and rk_r > 500)):
            puntos = 3
            nivel = "🔴 Rojo"
        elif rk_f <= 100 and (rk_r is None and wc_r or (rk_r and rk_r > 300)):
            puntos = 2
            nivel = "🟠 Naranja"
        elif rk_f <= 200 and (rk_r is None and wc_r or (rk_r and rk_r > 250)):
            puntos = 1
            nivel = "🟡 Amarillo"
        else:
            continue

        rival_txt = f"Rank #{rk_r}" if rk_r else "sin ranking"
        wc_txt = " (Wild Card)" if wc_r else ""
        detalle = f"{nivel}: {nom_f} (Rank #{rk_f}) vs {nom_r}{wc_txt} ({rival_txt})"
        return True, detalle, lado, puntos

    return False, "", None, 0


# ---------------------------------------------------------------------------
# SEÑAL 6: DESCANSO
# ---------------------------------------------------------------------------
def evaluar_descanso(partidos_a, id_a, partidos_b, id_b):
    """Evalúa si un equipo descansó más que el otro."""
    def _dias_ultimo_partido(partidos, id_equipo):
        for p in partidos[:3]:
            dias = calcular_dias_atras(p.get("fecha", ""))
            if dias < 90:
                return dias
        return 999

    dias_a = _dias_ultimo_partido(partidos_a, id_a)
    dias_b = _dias_ultimo_partido(partidos_b, id_b)

    if dias_a == 999 or dias_b == 999:
        return None

    if dias_a - dias_b >= 4:
        return {"favorito": LOCAL, "dias_a": dias_a, "dias_b": dias_b,
                "detalle": f"Descanso: local descansó {dias_a}d vs visita {dias_b}d"}
    if dias_b - dias_a >= 4:
        return {"favorito": VISITA, "dias_a": dias_a, "dias_b": dias_b,
                "detalle": f"Descanso: visita descansó {dias_b}d vs local {dias_a}d"}
    return None


# ---------------------------------------------------------------------------
# SEÑAL 8: MOMENTUM (racha)
# ---------------------------------------------------------------------------
def evaluar_momentum(partidos, id_equipo):
    """Calcula la racha de victorias consecutivas."""
    racha = 0
    for p in partidos[:6]:
        if calcular_dias_atras(p.get("fecha", "")) > 90:
            continue
        es_local = p.get("id_local") == id_equipo
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")
        if pts_prop is None or pts_riv is None:
            break
        if pts_prop > pts_riv:
            racha += 1
        else:
            break
    return racha


# ---------------------------------------------------------------------------
# MERCADO SUGERIDO
# ---------------------------------------------------------------------------
def sugerir_mercado(deporte, favorito, nombre_fav=None):
    fav = nombre_fav or favorito
    if deporte == "Soccer":
        return f"Hándicap asiático {fav} (-1.5) o victoria directa"
    if deporte == "Volleyball":
        return f"Hándicap de sets {fav} (-2.5 sets) o hándicap de puntos"
    if deporte in ("Basketball", "Handball", "Rugby"):
        return f"Hándicap de puntos {fav} o ganador al descanso"
    if deporte == "Tennis":
        return f"{fav}: hándicap de juegos o 2-0 en sets"
    if deporte in ("Floorball", "Futsal", "Ice Hockey", "Waterpolo", "Field Hockey"):
        return f"Hándicap {fav} (-2.5) o victoria directa en tiempo regular"
    if deporte in ("Table Tennis", "Badminton"):
        return f"{fav} gana sin ceder sets (2-0 / 3-0)"
    return f"Victoria directa {fav} / hándicap"


# ---------------------------------------------------------------------------
# DECISIÓN FINAL
# ---------------------------------------------------------------------------
def evaluar_mismatch(deporte, perf_local, perf_visita, triangulaciones, h2h,
                     tabla_local_visita=None, datos_extra=None):
    """
    Suma puntos por lado con las 9 señales.
    Devuelve un dict con: hay_mismatch, favorito, puntaje, alertas, confianza.
    """
    puntos = {LOCAL: 0, VISITA: 0}
    textos = {LOCAL: [], VISITA: []}

    def sumar(lado, pts, texto):
        puntos[lado] += pts
        textos[lado].append(texto)

    # Señal 1: Tabla (2 pts)
    if tabla_local_visita and tabla_local_visita.get("es_mismatch_tabla"):
        sumar(tabla_local_visita["favorito"], 2, tabla_local_visita["detalle"])

    # Señal 2: Forma reciente (2 pts base + 1 extra)
    umbral = obtener_umbral_deporte(deporte)
    if umbral is not None:
        perf = {LOCAL: perf_local, VISITA: perf_visita}
        for fav in (LOCAL, VISITA):
            pf, pr = perf[fav], perf[_otro(fav)]
            if pf["muestras"] >= 4 and pr["muestras"] >= 4 and pf["victorias"] >= 3 and pr["derrotas"] >= 3:
                brecha = pf["dif_prom"] - pr["dif_prom"]
                if brecha >= umbral:
                    extra = 1 if brecha >= umbral * 2 else 0
                    sumar(fav, 2 + extra, (
                        f"Forma: {fav} {pf['dif_prom']:+} por partido "
                        f"({pf['victorias']}V en {pf['muestras']}) vs rival "
                        f"{pr['dif_prom']:+} ({pr['derrotas']}D en {pr['muestras']})"
                    ))

    # Señal 3: Triangulación (1-3 pts)
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

    # Señal 4: H2H extendido (1-3 pts)
    if h2h:
        for fav in (LOCAL, VISITA):
            recientes = [x for x in h2h.get("reciente", []) if x["ganador"] == fav]
            medios = [x for x in h2h.get("medio", []) if x["ganador"] == fav]
            viejos = [x for x in h2h.get("viejo", []) if x["ganador"] == fav]
            total_fav = len(recientes) + len(medios) + len(viejos)
            if total_fav >= 2:
                pts = 2 if recientes else (1 if medios else 0.5)
                detalle = f"H2H: {fav} ganó {total_fav} cruces ("
                partes = []
                if recientes: partes.append(f"{len(recientes)} recientes")
                if medios: partes.append(f"{len(medios)} 6-18m")
                if viejos: partes.append(f"{len(viejos)} +18m")
                detalle += ", ".join(partes) + ")"
                sumar(fav, pts, detalle)

    # Señal 6: Descanso (0-1 pt)
    if datos_extra and datos_extra.get("descanso"):
        d = datos_extra["descanso"]
        sumar(d["favorito"], 1, d["detalle"])

    # Señal 8: Momentum (0-2 pts)
    if datos_extra:
        racha_loc = datos_extra.get("racha_local", 0)
        racha_vis = datos_extra.get("racha_visita", 0)
        if racha_loc >= 4:
            sumar(LOCAL, 2 if racha_loc >= 6 else 1, f"Momentum: {LOCAL} {racha_loc} victorias seguidas")
        if racha_vis >= 4:
            sumar(VISITA, 2 if racha_vis >= 6 else 1, f"Momentum: {VISITA} {racha_vis} victorias seguidas")

    # Decisión
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
    elif puntaje_contra > 1:
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
        resultado.update({
            "hay_mismatch": True,
            "favorito": favorito,
            "alertas": textos[favorito],
            "confianza": confianza,
        })
    return resultado