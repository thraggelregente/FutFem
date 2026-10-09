"""
motor_mismatches.py
Cerebro Cuantitativo y Matemático Multideporte Femenino:
- 14 disciplinas con umbrales calibrados por tipo de tanteador.
- Disparadores directos independientes:
  1. Tabla de posiciones de la temporada vigente (Puntero vs Colista).
  2. Triangulación de Rivales en Común (A le ganó a C y B perdió con C).
  3. Contraste de Forma Reciente (Rachas y diferencial de los últimos partidos).
  4. H2H Reciente (Últimos 12 meses).
  5. Tenis: Asimetría por Wild Card (WC) / sin ranking vs Pro consolidada.
"""

from datetime import datetime

def calcular_dias_atras(fecha_str):
    """Filtra partidos viejos respetando la regla de forma vigente."""
    try:
        fecha_p = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
        return max(0, (datetime.utcnow() - fecha_p).days)
    except Exception:
        return 999


def obtener_umbral_deporte(deporte):
    """
    Define el margen mínimo de brecha neta para disparar alerta
    según la dinámica del tanteador de cada deporte.
    """
    umbrales = {
        # Deportes de bajo tanteador (goles netos)
        "Soccer": 2.0,
        "Futsal": 2.5,
        "Ice Hockey": 2.5,
        "Floorball": 3.5,
        "Waterpolo": 3.0,
        "Field Hockey": 2.5,

        # Deportes de sets / puntos intermedios
        "Handball": 5.0,
        "Volleyball": 12.0,       # Diferencia acumulada en puntos de sets
        "Table Tennis": 8.0,
        "Badminton": 8.0,

        # Deportes de alto tanteador
        "Basketball": 14.0,
        "Rugby": 15.0,
        "Cricket": 20.0
    }
    return umbrales.get(deporte, 5.0)


def evaluar_tabla_posiciones(tabla_data, id_local, id_visita):
    """
    Evalúa la posición, puntos y diferencia en la tabla de la temporada actual.
    """
    if not tabla_data or id_local not in tabla_data or id_visita not in tabla_data:
        return None

    tl = tabla_data[id_local]
    tv = tabla_data[id_visita]

    pj_l = max(1, tl.get("partidos_jugados", 1))
    pj_v = max(1, tv.get("partidos_jugados", 1))

    ppg_local = tl.get("puntos", 0) / pj_l
    ppg_visita = tv.get("puntos", 0) / pj_v

    delta_posiciones = tv.get("posicion", 0) - tl.get("posicion", 0)

    # Disparador: Puntero/Top 3 vs Colista/Zona baja, o brecha de >= 7 puestos
    es_asimetria = False
    detalle = ""

    if (tl.get("posicion", 99) <= 3 and tv.get("posicion", 0) >= 8) or delta_posiciones >= 7:
        if ppg_local >= 1.7 and ppg_visita <= 0.9:
            es_asimetria = True
            detalle = (
                f"Líder/Top vs Colista: Local {tl['posicion']}° ({round(ppg_local, 2)} pts/partido, dif {tl.get('dif_neta', 0)}) vs "
                f"Visita {tv['posicion']}° ({round(ppg_visita, 2)} pts/partido, dif {tv.get('dif_neta', 0)})"
            )

    return {
        "es_mismatch_tabla": es_asimetria,
        "detalle": detalle,
        "delta_posiciones": delta_posiciones
    }


def evaluar_rendimiento_reciente(partidos, id_equipo):
    """
    Evalúa los últimos 6 partidos (máximo 45 días de antigüedad).
    """
    if not partidos:
        return {"dif_prom": 0.0, "victorias": 0, "derrotas": 0, "muestras": 0}

    diferencias = []
    victorias = 0
    derrotas = 0

    for p in partidos[:6]:
        if calcular_dias_atras(p.get("fecha", "")) > 45:
            continue

        es_local_hist = p.get("id_local") == id_equipo
        pts_prop = p.get("puntos_local") if es_local_hist else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local_hist else p.get("puntos_local")

        if pts_prop is not None and pts_riv is not None:
            dif = pts_prop - pts_riv
            diferencias.append(dif)
            if dif > 0:
                victorias += 1
            elif dif < 0:
                derrotas += 1

    prom_dif = sum(diferencias) / len(diferencias) if diferencias else 0.0
    return {
        "dif_prom": round(prom_dif, 2),
        "victorias": victorias,
        "derrotas": derrotas,
        "muestras": len(diferencias)
    }


def triangular_rivales(partidos_a, id_a, partidos_b, id_b):
    """
    Triangulación A -> C -> B (últimos 60 días).
    Detecta si A superó a un rival C y B cayó ante ese mismo rival C.
    """
    historial_a = {}
    for p in partidos_a[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 60:
            continue

        es_local = p.get("id_local") == id_a
        rival_id = p.get("id_visita") if es_local else p.get("id_local")
        rival_nom = p.get("nom_visita") if es_local else p.get("nom_local")
        pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
        pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")

        if rival_id and pts_prop is not None and pts_riv is not None:
            historial_a[rival_id] = {
                "nombre": rival_nom,
                "gano": pts_prop > pts_riv,
                "dif": pts_prop - pts_riv
            }

    triangulaciones = []
    for p in partidos_b[:8]:
        if calcular_dias_atras(p.get("fecha", "")) > 60:
            continue

        es_local = p.get("id_local") == id_b
        rival_id = p.get("id_visita") if es_local else p.get("id_local")

        if rival_id in historial_a:
            pts_prop = p.get("puntos_local") if es_local else p.get("puntos_visita")
            pts_riv = p.get("puntos_visita") if es_local else p.get("puntos_local")

            if pts_prop is not None and pts_riv is not None:
                gano_b = pts_prop > pts_riv
                dif_b = pts_prop - pts_riv
                dato_a = historial_a[rival_id]

                # Señal clara: A le ganó a C y B perdió contra C
                if dato_a["gano"] and not gano_b:
                    brecha = dato_a["dif"] - dif_b
                    triangulaciones.append({
                        "rival": dato_a["nombre"],
                        "dif_a": dato_a["dif"],
                        "dif_b": dif_b,
                        "brecha": brecha
                    })

    return triangulaciones


def analizar_h2h_reciente(historial_h2h, id_local, id_visita):
    """Enfrentamientos directos de los últimos 12 meses."""
    h2h_validos = []
    for p in historial_h2h:
        if calcular_dias_atras(p.get("fecha", "")) <= 365:
            es_local_hist = p.get("id_local") == id_local
            pts_loc = p.get("puntos_local", 0)
            pts_vis = p.get("puntos_visita", 0)
            ganador = "Local" if (pts_loc > pts_vis if es_local_hist else pts_vis > pts_loc) else "Visita"
            h2h_validos.append({
                "ganador": ganador,
                "dif": abs(pts_loc - pts_vis)
            })
    return h2h_validos


def evaluar_mismatch_tenis(nombre_local, nombre_visita, rank_local, rank_visita):
    """
    Disparador quirúrgico para Tenis ITF / WTA:
    Wild Cards (WC) sin ranking o amateurs frente a profesionales en ritmo.
    """
    es_wc_local = "(wc)" in nombre_local.lower() or "[wc]" in nombre_local.lower()
    es_wc_visita = "(wc)" in nombre_visita.lower() or "[wc]" in nombre_visita.lower()

    if es_wc_local and not es_wc_visita:
        if (not rank_local or rank_local > 900) and (rank_visita and rank_visita < 450):
            return True, f"Wild Card Asimétrico: Local invitada ({nombre_local}) sin ranking competitivo vs Visita regular (Rank #{rank_visita})"

    if es_wc_visita and not es_wc_local:
        if (not rank_visita or rank_visita > 900) and (rank_local and rank_local < 450):
            return True, f"Wild Card Asimétrico: Visita invitada ({nombre_visita}) sin ranking competitivo vs Local consolidada (Rank #{rank_local})"

    return False, ""


def sugerir_mercado(deporte, alertas, es_favorito_local=True):
    """Genera la recomendación de apuesta según la disciplina."""
    fav = "Local" if es_favorito_local else "Visitante"
    
    if deporte == "Soccer":
        return f"Hándicap Asiático {fav} (-1.5 / -2.0) o Victoria Directa + Over 2.5 goles"
    elif deporte == "Volleyball":
        return f"Hándicap de Sets {fav} (-2.5 sets / Gana 3-0) o Hándicap de Puntos (-15.5)"
    elif deporte in ["Basketball", "Handball"]:
        return f"Hándicap de Puntos {fav} o Línea de Ganador al Descanso"
    elif deporte == "Tennis":
        return f"Under Total de Juegos (Games) o Hándicap -6.5 Juegos {fav} / 2-0 Sets"
    elif deporte in ["Floorball", "Futsal", "Ice Hockey", "Waterpolo"]:
        return f"Hándicap {fav} (-2.5) o Victoria Directa en Tiempo Regular"
    
    return f"Victoria Directa {fav} / Hándicap"


def evaluar_mismatch(deporte, perf_local, perf_visita, triangulaciones, h2h, tabla_local_visita=None):
    """
    Disparadores lógicos independientes. Si salta una sola señal sólida, confirma mismatch.
    """
    alertas = []

    # 1. Trigger Tabla Vigente
    if tabla_local_visita and tabla_local_visita.get("es_mismatch_tabla"):
        alertas.append(tabla_local_visita["detalle"])

    # 2. Trigger Triangulación A-C-B
    if triangulaciones:
        mejor = triangulaciones[0]
        alertas.append(
            f"Triangulación Directa vs {mejor['rival']}: Local superó por +{mejor['dif_a']} | Visita cayó por {mejor['dif_b']}"
        )

    # 3. Trigger Forma y Racha Reciente
    if perf_local["victorias"] >= 3 and perf_visita["derrotas"] >= 3:
        brecha = perf_local["dif_prom"] - perf_visita["dif_prom"]
        umbral = obtener_umbral_deporte(deporte)
        if brecha >= umbral:
            alertas.append(f"Contraste de Forma Reciente: Local +{perf_local['dif_prom']} vs Visita {perf_visita['dif_prom']}")

    # 4. Trigger H2H Reciente
    if h2h and len(h2h) >= 1:
        victorias_loc = sum(1 for x in h2h if x["ganador"] == "Local")
        if victorias_loc == len(h2h):
            alertas.append(f"Dominio H2H Reciente: Local ganó {victorias_loc}/{len(h2h)} cruces en los últimos 12 meses")

    hay_mismatch = len(alertas) > 0
    pick = sugerir_mercado(deporte, alertas, es_favorito_local=True) if hay_mismatch else ""
    return hay_mismatch, alertas, pick