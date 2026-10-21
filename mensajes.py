"""Presentación HTML para Telegram; conserva evidencia y distingue candidatos."""
import html
import re

DEPORTES = {"Soccer": ("⚽", "Fútbol"), "Basketball": ("🏀", "Básquet"),
            "Tennis": ("🎾", "Tenis"), "Ice Hockey": ("🏒", "Hockey sobre hielo"),
            "Handball": ("🤾", "Handball"), "Volleyball": ("🏐", "Vóley"), "Rugby": ("🏉", "Rugby"),
            "Softball": ("🥎", "Softball"), "Lacrosse": ("🥍", "Lacrosse"), "Field Hockey": ("🏑", "Hockey sobre césped"), "Cricket": ("🏏", "Cricket")}
FUENTES = {"wta": "WTA", "WTA oficial": "WTA", "WTA historial oficial": "WTA",
           "tennis_api": "Tennis API", "Tennis API": "Tennis API",
           "cricsheet": "Cricsheet", "balldontlie": "BALLDONTLIE",
           "sportapi": "SportAPI.ai",
           "worldrugby": "World Rugby",
           "sportscore": "SportScore",
           "tauron": "TAURON Liga Kobiet oficial", "lvf": "LVF oficial", "lnv": "LNV oficial",
           "fivb": "FIVB/VIS", "cev": "CEV", "bbs": "Big Balls Sports Data", "Big Balls Sports Data": "Big Balls Sports Data",
           "pwhl": "PWHL", "espn": "ESPN", "highlightly": "Highlightly", "api_sports": "API-Sports",
           "openligadb": "OpenLigaDB", "thesportsdb": "TheSportsDB", "oddspapi": "OddsPapi",
           "theoddsapi": "The Odds API", "The Odds API": "The Odds API"}


def fuentes_legibles(fuentes):
    salida = []
    for fuente in fuentes or []:
        raw = str(fuente)
        nombre = FUENTES.get(raw)
        if nombre is None:
            nombre = next((v for k, v in FUENTES.items() if raw.lower().startswith(k.lower())), raw)
        if nombre not in salida:
            salida.append(nombre)
    return " · ".join(salida) or "Sin fuente verificada"


def evidencia_clara(texto, local, visita, destacado):
    """Aclarar evidencia existente sin agregar puntos ni inferencias deportivas."""
    otro = visita if destacado == local else local
    m = re.fullmatch(r'Ranking (.+): (\d+); (.+); fecha (.+)', texto)
    if m:
        jugadora, ranking, fuente, fecha = m.groups()
        return f'{jugadora}: puesto #{ranking}. Fuente: {fuente}. Ranking del {fecha}.'
    m = re.fullmatch(r"Triangulación vs (.+): ganó por ([+-]?\d+(?:\.\d+)?) y el rival cayó por ([+-]?\d+(?:\.\d+)?) \((\d+) rival/es en común\)", texto)
    if m:
        rival, gano, perdio, n = m.groups()
        return (f"Resultados frente a rivales comunes: se encontraron {n} rivales compartidas. "
                f"Frente a {rival}, {destacado} ganó por {gano.lstrip('+-')} (margen {gano}) "
                f"y {otro} perdió por {perdio.lstrip('+-')} (margen {perdio}).")
    m = re.fullmatch(r"Calendario: (local|visita) jugó (\d+) partidos en (\d+) días vs (\d+) (?:del|de la) (local|visita)", texto)
    if m:
        lado, n, dias, n_otro, lado_otro = m.groups()
        nombres = {"local": local, "visita": visita}
        return (f"Carga de partidos: {nombres[lado]} jugó {n} encuentros en {dias} días; "
                f"{nombres[lado_otro]}, {n_otro}. El calendario muestra mayor carga reciente para {nombres[lado]}.")
    m = re.fullmatch(r"Elo: (Local|Visitante) ([\d.]+) vs ([\d.]+) \(ajuste de localía; (\d+)/(\d+) partidos en el libro\)", texto)
    if m:
        lado, elo_f, elo_r, n_local, n_visita = m.groups()
        fav, rival = (local, visita) if lado == "Local" else (visita, local)
        return (f"Valoración Elo: {fav} {elo_f} puntos frente a {rival} {elo_r}, con ajuste de localía. "
                f"El registro del bot contiene {n_local} partidos de {local} y {n_visita} de {visita}.")
    m = re.fullmatch(r"Descanso: (local|visita) descansó (\d+)d vs (local|visita) (\d+)d", texto)
    if m:
        lado, dias, lado_otro, dias_otro = m.groups()
        nombres = {"local": local, "visita": visita}
        return f"Descanso desde el último partido registrado: {nombres[lado]} {dias} días; {nombres[lado_otro]} {dias_otro} días."
    m = re.fullmatch(r"Forma: (Local|Visitante) ([+-]?[\d.]+) por partido \((\d+)V en (\d+)\) vs rival ([+-]?[\d.]+) \((\d+)D en (\d+)\)", texto)
    if m:
        lado, media_f, victorias, muestra_f, media_r, derrotas, muestra_r = m.groups()
        fav, rival = (local, visita) if lado == "Local" else (visita, local)
        return (f"Forma reciente: {fav}, diferencia media ajustada {media_f} por partido "
                f"({victorias} victorias en {muestra_f} partidos); {rival}, {media_r} "
                f"({derrotas} derrotas en {muestra_r} partidos).")
    m = re.fullmatch(r"H2H: (Local|Visitante) ganó (\d+) cruces \((.+)\)(?: vs (\d+) del rival)?", texto)
    if m:
        lado, ganados, periodos, rival_ganados = m.groups()
        fav, rival = (local, visita) if lado == "Local" else (visita, local)
        periodos = periodos.replace("6-18m", "de 6 a 18 meses").replace("+18m", "de más de 18 meses")
        salida = f"Enfrentamientos directos: {fav} ganó {ganados} cruces ({periodos})."
        if rival_ganados:
            salida += f" {rival} ganó {rival_ganados}."
        return salida
    m = re.fullmatch(r"Momentum: (Local|Visitante) (\d+) victorias seguidas", texto)
    if m:
        lado, n = m.groups()
        return f"Racha reciente: {local if lado == 'Local' else visita} acumula {n} victorias consecutivas."
    m = re.fullmatch(r"Plantel: (Local|Visitante) con (\d+) bajas confirmadas vs (\d+) de (Local|Visitante)", texto)
    if m:
        lado, n, n_otro, lado_otro = m.groups()
        nombres = {"Local": local, "Visitante": visita}
        return f"Plantel: {nombres[lado]} tiene {n} bajas confirmadas; {nombres[lado_otro]}, {n_otro}."
    if texto.startswith("Tabla: "):
        return f"Clasificación ({destacado} frente a {otro}): " + texto[len("Tabla: "):]
    return texto  # formatos desconocidos se conservan completos


def evaluacion_clara(texto):
    m = re.fullmatch(r"Magnitud: ([^;]+); calidad: ([^;]+)(?:; (\d+) familia\(s\) de señales, sin independencia garantizada)?", str(texto))
    if not m:
        return "<b>Evaluación:</b> " + html.escape(str(texto))
    magnitud, calidad, familias = m.groups()
    significado = ('Faltan datos comparables para confirmar la ventaja.' if calidad.lower() == 'limitada'
                   else 'Hay contexto deportivo suficiente según las reglas del detector; no es una probabilidad de acierto.')
    salida = (f"<b>Magnitud del desnivel:</b> {html.escape(magnitud.lower())}.\n"
              f"<b>Respaldo de los datos:</b> {html.escape(calidad)}. {significado}")
    if familias:
        salida += (f"\n{familias} familia(s) de señales. Pueden compartir información; "
                   "no equivalen a pruebas independientes.")
    return salida


def alerta(deporte, torneo, local, visita, hora, evidencias, nombre_destacado, evaluacion, fuentes, tipo, analisis=None):
    esc = lambda v: html.escape(str(v))
    emoji, nombre = DEPORTES.get(deporte, ("🏅", deporte))
    candidato = "CANDIDATO" in tipo.upper()
    titulo = "Candidato por ranking" if candidato and "RANKING" in tipo.upper() else "Candidato deportivo" if candidato else "Asimetría deportiva"
    if "EXPERIMENTAL" in tipo.upper():
        titulo = "Asimetría · evaluación experimental"
    etiqueta = "Jugadora mejor posicionada" if candidato and "RANKING" in tipo.upper() else "Lado a evaluar" if candidato else "Jugadora con ventaja detectada" if deporte == "Tennis" else "Equipo con ventaja detectada"
    detalles = list(dict.fromkeys(evidencia_clara(str(d), local, visita, nombre_destacado) for d in evidencias or []))
    analisis = analisis or {}
    detalles += [str(d) for d in analisis.get('evidencia',[]) if str(d) not in detalles]
    lectura = (f"{nombre_destacado} tiene mejor ranking. La diferencia todavía no está confirmada con suficiente contexto deportivo."
               if candidato and 'RANKING' in tipo.upper() else
               f"Las señales disponibles apuntan hacia {nombre_destacado}. La magnitud describe el desnivel detectado, no un marcador previsto.")
    recomendaciones=[]
    for pick in analisis.get('selecciones',[]):
        recomendaciones.append('• <b>'+esc(pick['mercado'])+': '+esc(pick['seleccion'])+'</b>\n'+esc(pick['motivo']))
    if not recomendaciones:
        recomendaciones=['<b>Sin apuesta recomendada por ahora.</b>']
    recomendaciones.append(esc(analisis.get('criterio') or 'Esta alerta no tiene una selección de mercado respaldada por datos suficientes.'))
    if analisis.get('selecciones'):
        recomendaciones.append('Orientación deportiva, sin cuotas ni rentabilidad calculada. No se propone resultado exacto ni tamaño de apuesta.')
    faltantes=list(dict.fromkeys(analisis.get('faltantes',[])))
    cobertura = [d for d in detalles if d.startswith(('Historial oficial registrado','Historial registrado en las fuentes',
                'Tennis API:')) or ': contexto Tennis API WTA/ITF;' in d]
    detalles = [d for d in detalles if d not in cobertura]
    cobertura_txt = ('\n\n<b>Cobertura y límites</b>\n'+'\n'.join('• '+esc(d) for d in cobertura)) if cobertura else ''
    limites=('\n\n<b>Qué falta comprobar</b>\n'+'\n'.join('• '+esc(d) for d in faltantes)) if faltantes else ''
    credito = '\n<a href="https://sportscore.com/">Powered by SportScore</a>' if any("sportscore" in str(f).lower() for f in fuentes or []) else ""
    if any("cricsheet" in str(f).lower() for f in fuentes or []):
        credito += '\nHistorial resumido de <a href="https://cricsheet.org/">Cricsheet</a> · <a href="https://opendatacommons.org/licenses/by/1.0/">ODC-By</a>'
    return (
        f"{emoji} <b>{titulo} · {esc(nombre)} femenino</b>\n\n"
        f"<b>{esc(local)} vs {esc(visita)}</b>\n"
        f"{esc(torneo)}\n"
        f"🕒 {esc(hora)}\n\n"
        f"<b>Lectura rápida</b>\n{esc(lectura)}\n\n"
        f"<b>{etiqueta}:</b> {esc(nombre_destacado)}\n"
        f"{evaluacion_clara(evaluacion)}\n\n"
        "<b>Datos que encontramos</b>\n" + "\n".join("• " + esc(d) for d in detalles) + limites +
        "\n\n<b>Recomendaciones</b>\n"+'\n'.join(recomendaciones) + cobertura_txt +
        f"\n\n<i>Fuentes: {esc(fuentes_legibles(fuentes))}</i>{credito}"
    )


def dividir_html(texto, limite=3500):
    """Partes pequeñas con HTML balanceado, entidades enteras y sin recortar datos.

El límite se aplica a unidades UTF-16 del HTML completo, más conservador que el
límite visible de Telegram. Las alertas sólo generan b, i y a.
"""
    unidades = lambda t: len(t.encode("utf-16-le")) // 2
    if unidades(texto) <= limite:
        return [texto]
    if limite < 256:
        raise ValueError("límite insuficiente")
    partes, actual, pila, n = [], [], [], 0
    tokens = re.findall(r"<[^>]+>|&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z]+);|.", texto, re.S)
    for token in tokens:
        nueva = list(pila)
        if token.startswith("<"):
            cerrar = re.fullmatch(r"</(b|i|a)>", token)
            abrir = re.fullmatch(r"<(b|i|a)(?:\s[^>]*)?>", token)
            if cerrar:
                if not nueva or nueva[-1][0] != cerrar[1]:
                    raise ValueError("HTML desbalanceado")
                nueva.pop()
            elif abrir:
                nueva.append((abrir[1], token))
            else:
                raise ValueError("etiqueta HTML no admitida")
        cierre = "".join(f"</{tag}>" for tag, _ in reversed(nueva))
        if n + unidades(token) + unidades(cierre) > limite:
            partes.append("".join(actual) + "".join(f"</{tag}>" for tag, _ in reversed(pila)))
            actual = [apertura for _, apertura in pila]
            n = sum(unidades(t) for t in actual)
        actual.append(token)
        n += unidades(token)
        pila = nueva
    if pila:
        raise ValueError("HTML desbalanceado")
    if actual:
        partes.append("".join(actual))
    return [f"<i>Alerta · parte {i}/{len(partes)}</i>\n" + p for i, p in enumerate(partes, 1)]


def inicio(fuentes, deportes, intervalo):
    nombres = [DEPORTES.get(d, ("", d))[1] for d in deportes]
    return ("🟢 <b>Radar femenino en marcha</b>\n\n"
            f"<b>{len(nombres)} deportes</b> · Revisión cada {max(1, intervalo // 60)} min\n"
            f"{html.escape(' · '.join(nombres))}\n\n"
            f"<b>Fuentes</b>\n{html.escape(fuentes_legibles(fuentes))}\n\n"
            "<i>Alertas por diferencias deportivas. La cobertura varía según la competición.</i>")
