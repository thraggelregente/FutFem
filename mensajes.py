"""Presentación HTML para Telegram; conserva evidencia y distingue candidatos."""
import html

DEPORTES = {"Soccer": ("⚽", "Fútbol"), "Basketball": ("🏀", "Básquet"),
            "Tennis": ("🎾", "Tenis"), "Ice Hockey": ("🏒", "Hockey sobre hielo"),
            "Handball": ("🤾", "Handball"), "Volleyball": ("🏐", "Vóley"), "Rugby": ("🏉", "Rugby"),
            "Softball": ("🥎", "Softball"), "Lacrosse": ("🥍", "Lacrosse"), "Field Hockey": ("🏑", "Hockey sobre césped")}
FUENTES = {"wta": "WTA", "WTA oficial": "WTA", "WTA historial oficial": "WTA",
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


def alerta(deporte, torneo, local, visita, hora, evidencias, nombre_destacado, evaluacion, fuentes, tipo):
    esc = lambda v: html.escape(str(v))
    emoji, nombre = DEPORTES.get(deporte, ("🏅", deporte))
    candidato = "CANDIDATO" in tipo.upper()
    titulo = "Candidato por ranking" if candidato and "RANKING" in tipo.upper() else "Candidato deportivo" if candidato else "Asimetría deportiva"
    if "EXPERIMENTAL" in tipo.upper():
        titulo = "Asimetría · evaluación experimental"
    etiqueta = "Mejor ranking" if candidato and "RANKING" in tipo.upper() else "Lado a evaluar" if candidato else "Ventaja observada"
    detalles = list(dict.fromkeys(str(d) for d in evidencias or []))[:10]
    return (
        f"{emoji} <b>{titulo} · {esc(nombre)} femenino</b>\n\n"
        f"<b>{esc(local)} vs {esc(visita)}</b>\n"
        f"{esc(torneo)}\n"
        f"🕒 {esc(hora)}\n\n"
        f"<b>{etiqueta}:</b> {esc(nombre_destacado)}\n"
        f"{esc(evaluacion)}\n\n"
        "<b>Qué encontramos</b>\n" + "\n".join("• " + esc(d) for d in detalles) +
        f"\n\n<i>Fuentes: {esc(fuentes_legibles(fuentes))}</i>"
    )


def inicio(fuentes, deportes, intervalo):
    nombres = [DEPORTES.get(d, ("", d))[1] for d in deportes]
    return ("🟢 <b>Radar femenino en marcha</b>\n\n"
            f"<b>{len(nombres)} deportes</b> · Revisión cada {max(1, intervalo // 60)} min\n"
            f"{html.escape(' · '.join(nombres))}\n\n"
            f"<b>Fuentes</b>\n{html.escape(fuentes_legibles(fuentes))}\n\n"
            "<i>Alertas por diferencias deportivas. La cobertura varía según la competición.</i>")
