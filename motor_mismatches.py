"""
motor_mismatches.py
Cerebro cuantitativo del Radar Femenino (simétrico: el favorito puede ser local o visitante).

Señales independientes, cada una suma puntos al lado al que favorece:
  1. Tabla de la temporada vigente (efectividad + brecha de posiciones)   -> 2 pts
  2. Contraste de forma reciente (rachas + diferencial por partido)       -> 2 pts
  3. Triangulación de rivales en común (A le ganó a C, B perdió con C)    -> 1-2 pts
  4. H2H de los últimos 12 meses (mismo ganador en todos los cruces)      -> 1-2 pts
  5. Tenis: asimetría de ranking / Wild Card (función aparte)

Se dispara alerta solo si un lado suma >= PUNTAJE_MINIMO y el otro lado suma 0
(sin señales contradictorias). Confianza: Media (3-4 pts) / Alta (>= 5 pts).
"""

import os
from datetime import datetime, timezone

LOCAL = "Local"
VISITA = "Visitante"
EMPATE = "Empate"

PUNTAJE_MINIMO = int(os.environ.get("PUNTAJE_MINIMO", "3"))
PUNTAJE_ALTA = 5
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
    """
    Brecha mínima de diferencial promedio (local - visita) para considerar
    contraste de forma. Es la suma de ambos márgenes, por eso es "alta".
    En vóley / tenis de mesa / bádminton el marcador son SETS (no puntos).
    None = no usar el diferencial (cricket: runs no comparables entre formatos).
    """
    umbrales = {
        # Bajo tanteador (goles)
        "Soccer": 2.0,
        "Futsal": 3.0,
        "Ice Hockey": 2.5,
        "Floorball": 3.5,
        "Waterpolo": 4.0,
        "Field Hockey": 2.5,
        # Sets
        "Volleyball": 3.0,
        "Table Tennis": 3.0,
        "Badminton": 2.5,
        # Tanteador medio / alto
        "Handball": 8.0,
        "Basketball": 20.0,
        "Rugby": 20.0,
        "Cricket": None,
    }
    return umbrales.get(deporte, 5.0)


# ---------------------------------------------------------------------------
# 1. TABLA
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
                f"Tabla: líder/top {tf['posicion']}° ({round(rf * 100)}% de efectividad, "
                f"dif {tf.get('dif_neta', 0):+}) vs zona baja {tr['posicion']}° "
                f"({round(rr * 100)}%, dif {tr.get('dif_neta', 0):+})"
            ),
        }
    return None


def evaluar_tabla_posiciones(tabla_data, id_local, id_visita):
    """
    Usa la efectividad (% de victorias, empate = 0.5) en lugar de puntos por partido,
    así funciona igual en fútbol (3 pts), básquet, vóley, etc.
    """
    if not tabla_data or id_local not in tabla_data or id_visita not in tabla_data:
        return None

    n = len(tabla_data)
    for lado, id_f, id_r in ((LOCAL, id_local, id_visita), (VISITA, id_visita, id_local)):
        res = _evaluar_tabla_lado(tabla_data, id_f, id_r, n)
        if res:
            return {
                "es_mismatch_tabla": True,
                "favorito": lado,
                "detalle": res["detalle"],
                "delta_posiciones": res["brecha"],
            }

    return {"es_mismatch_tabla": False, "favorito": None, "detalle": "", "delta_posiciones": 0}


# ---------------------------------------------------------------------------
# 2. FORMA RECIENTE
# ---------------------------------------------------------------------------
def evaluar_rendimiento_reciente(partidos, id_equipo):
    """Últimos 6 partidos terminados (máximo 45 días de antigüedad)."""
    vacio = {"dif_prom": 0.0, "victorias": 0, "derrotas": 0, "muestras": 0}
    if not partidos:
        return vacio

    diferencias, victorias, derrotas = [], 0, 0
    for p in partidos[:6]:
        if calcular_dias_atras(p.get("fecha", "")) > 45:
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
        "victorias": victorias,
        "derrotas": derrotas,
        "muestras": len(diferencias),
    }


# ---------------------------------------------------------------------------
# 3. TRIANGULACIÓN
# ---------------------------------------------------------------------------
def _triangular_direccional(partidos_a, id_a, partidos_b, id_b):
    """A le ganó a C y B perdió con ese mismo C (últimos 60 días)."""
    historial_a = {}
    for p in partidos_a[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 60:
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
        if calcular_dias_atras(p.get("fecha", "")) > 60:
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
        # B tiene que haber PERDIDO (un empate no cuenta como derrota)
        if dato_a["gano"] and dif_b < 0:
            vistos.add(rival_id)
            resultado.append({
                "rival": dato_a["nombre"],
                "dif_a": dato_a["dif"],
                "dif_b": dif_b,
                "brecha": dato_a["dif"] - dif_b,
            })
    return resultado


def triangular_rivales(partidos_local, id_local, partidos_visita, id_visita):
    """Devuelve las triangulaciones a favor de cada lado: {'local': [...], 'visita': [...]}."""
    return {
        "local": _triangular_direccional(partidos_local, id_local, partidos_visita, id_visita),
        "visita": _triangular_direccional(partidos_visita, id_visita, partidos_local, id_local),
    }


# ---------------------------------------------------------------------------
# 4. H2H
# ---------------------------------------------------------------------------
def analizar_h2h_reciente(historial_h2h, id_local, id_visita):
    """Cruces directos de los últimos 12 meses. Maneja empates y marcadores faltantes."""
    h2h_validos = []
    for p in historial_h2h or []:
        if calcular_dias_atras(p.get("fecha", "")) > 365:
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
        h2h_validos.append({"ganador": ganador, "dif": abs(pts_loc - pts_vis)})
    return h2h_validos


# ---------------------------------------------------------------------------
# 5. TENIS (ranking / Wild Card)
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


def _brecha_ranking(rank_fav, rank_rival, rival_es_wc):
    """La favorita debe ser una jugadora establecida y la rival mucho peor (o WC sin ranking)."""
    if rank_fav is None or rank_fav > 250:
        return False
    if rank_rival is None:
        # Sin ranking: solo lo tomo si está marcada como WC (si no, puede ser un dato faltante)
        return rival_es_wc
    return rank_rival >= max(rank_fav * 3, rank_fav + 250)


def evaluar_mismatch_tenis(nombre_local, nombre_visita, rank_local, rank_visita,
                           entry_local=None, entry_visita=None):
    """
    Devuelve (hay_mismatch, detalle, favorito). Simétrico.
    Ya NO depende de que "(WC)" figure en el nombre: se basa en la brecha de ranking
    y menciona la Wild Card si el dato está disponible.
    """
    rl, rv = _rank_valido(rank_local), _rank_valido(rank_visita)
    wc_l, wc_v = _es_wc(nombre_local, entry_local), _es_wc(nombre_visita, entry_visita)

    for lado, nom_f, rk_f, nom_r, rk_r, wc_r in (
        (LOCAL, nombre_local, rl, nombre_visita, rv, wc_v),
        (VISITA, nombre_visita, rv, nombre_local, rl, wc_l),
    ):
        if _brecha_ranking(rk_f, rk_r, wc_r):
            rival_txt = f"Rank #{rk_r}" if rk_r else "sin ranking"
            wc_txt = " (Wild Card)" if wc_r else ""
            return True, (
                f"Asimetría de ranking: {nom_f} (Rank #{rk_f}) vs {nom_r}{wc_txt} ({rival_txt})"
            ), lado

    return False, "", None


# ---------------------------------------------------------------------------
# MERCADO SUGERIDO
# ---------------------------------------------------------------------------
def sugerir_mercado(deporte, favorito, nombre_fav=None):
    fav = nombre_fav or favorito
    if deporte == "Soccer":
        return f"Hándicap asiático {fav} (-1.5) o victoria directa"
    if deporte == "Volleyball":
        return f"Hándicap de sets {fav} (-2.5 sets / gana 3-0) o hándicap de puntos"
    if deporte in ("Basketball", "Handball", "Rugby"):
        return f"Hándicap de puntos {fav} o ganador al descanso"
    if deporte == "Tennis":
        return f"{fav}: hándicap de juegos o 2-0 en sets (evaluar Under de games)"
    if deporte in ("Floorball", "Futsal", "Ice Hockey", "Waterpolo", "Field Hockey"):
        return f"Hándicap {fav} (-2.5) o victoria directa en tiempo regular"
    if deporte in ("Table Tennis", "Badminton"):
        return f"{fav} gana sin ceder sets (2-0 / 3-0)"
    return f"Victoria directa {fav} / hándicap"


# ---------------------------------------------------------------------------
# DECISIÓN FINAL
# ---------------------------------------------------------------------------
def evaluar_mismatch(deporte, perf_local, perf_visita, triangulaciones, h2h, tabla_local_visita=None):
    """
    Suma puntos por lado. Devuelve un dict:
      hay_mismatch, favorito (LOCAL/VISITA/None), puntaje, puntaje_contrario,
      alertas (textos del favorito), confianza, motivo_descarte
    """
    puntos = {LOCAL: 0, VISITA: 0}
    textos = {LOCAL: [], VISITA: []}

    def sumar(lado, pts, texto):
        puntos[lado] += pts
        textos[lado].append(texto)

    # 1. Tabla
    if tabla_local_visita and tabla_local_visita.get("es_mismatch_tabla"):
        sumar(tabla_local_visita["favorito"], 2, tabla_local_visita["detalle"])

    # 2. Forma reciente
    umbral = obtener_umbral_deporte(deporte)
    if umbral is not None:
        perf = {LOCAL: perf_local, VISITA: perf_visita}
        for fav in (LOCAL, VISITA):
            pf, pr = perf[fav], perf[_otro(fav)]
            if pf["muestras"] >= 4 and pr["muestras"] >= 4 and pf["victorias"] >= 3 and pr["derrotas"] >= 3:
                brecha = pf["dif_prom"] - pr["dif_prom"]
                if brecha >= umbral:
                    sumar(fav, 2, (
                        f"Forma reciente: {fav} {pf['dif_prom']:+} por partido "
                        f"({pf['victorias']}V en {pf['muestras']}) vs rival {pr['dif_prom']:+} "
                        f"({pr['derrotas']}D en {pr['muestras']})"
                    ))

    # 3. Triangulación (necesita >= 1 rival en común; 2 o más pesa el doble)
    for clave, fav in (("local", LOCAL), ("visita", VISITA)):
        lista = (triangulaciones or {}).get(clave) or []
        if lista:
            mejor = max(lista, key=lambda x: x["brecha"])
            extra = f" (+{len(lista) - 1} rival/es más)" if len(lista) > 1 else ""
            sumar(fav, 1 if len(lista) == 1 else 2, (
                f"Triangulación vs {mejor['rival']}: {fav} ganó por {mejor['dif_a']:+} "
                f"y el rival cayó por {mejor['dif_b']:+}{extra}"
            ))

    # 4. H2H (todos los cruces del último año a favor del mismo lado, mínimo 2)
    if h2h and len(h2h) >= 2:
        for fav in (LOCAL, VISITA):
            if all(x["ganador"] == fav for x in h2h):
                sumar(fav, 1 if len(h2h) == 2 else 2,
                      f"H2H: {fav} ganó {len(h2h)}/{len(h2h)} cruces en los últimos 12 meses")

    favorito = LOCAL if puntos[LOCAL] >= puntos[VISITA] else VISITA
    contrario = _otro(favorito)
    puntaje, puntaje_contra = puntos[favorito], puntos[contrario]

    resultado = {
        "hay_mismatch": False,
        "favorito": None,
        "puntaje": puntaje,
        "puntaje_contrario": puntaje_contra,
        "alertas": [],
        "confianza": "",
        "motivo_descarte": "",
    }

    if puntaje == 0:
        resultado["motivo_descarte"] = "sin señales"
    elif puntaje_contra > 0:
        resultado["motivo_descarte"] = f"señales contradictorias ({puntaje} vs {puntaje_contra})"
    elif puntaje < PUNTAJE_MINIMO:
        resultado["motivo_descarte"] = f"puntaje insuficiente ({puntaje}/{PUNTAJE_MINIMO})"
    else:
        resultado.update({
            "hay_mismatch": True,
            "favorito": favorito,
            "alertas": textos[favorito],
            "confianza": "Alta" if puntaje >= PUNTAJE_ALTA else "Media",
        })
    return resultado
