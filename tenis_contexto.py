"""Contexto de tenis WTA: efectividad por superficie y forma reciente.

Fuente: dataset abierto de Jeff Sackmann (github.com/JeffSackmann/tennis_wta, licencia CC BY-NC-SA 4.0,
uso no comercial), descargado como CSV desde raw.githubusercontent.com. No se evade ningÃºn control de
acceso ni se hace scraping: es un archivo pÃºblico versionado en GitHub.

Limitaciones que el mÃ³dulo respeta en vez de ocultar:
- El dataset se actualiza de forma irregular. La forma reciente solo cuenta partidos de los Ãºltimos
  120 dÃ­as; si el archivo estÃ¡ desactualizado, no hay seÃ±al de forma (no se inventa).
- La superficie del torneo sale de una tabla de torneos conocidos; si el torneo no estÃ¡ en la tabla,
  no se emite seÃ±al de superficie.
- Cada seÃ±al exige muestra mÃ­nima en AMBAS jugadoras; sin datos de una de ellas, no se emite nada.
- Esto AJUSTA el puntaje que ya dio el ranking (+/-); no genera alertas por sÃ­ solo.

Variables: TENIS_ANIOS (cuÃ¡ntos aÃ±os cargar, por defecto 2), TENIS_CONTEXTO_ACTIVO=0 lo apaga.
"""

from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime, timezone

import utilidades as U

BASE = os.environ.get("TENIS_DATASET_URL", "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/wta_matches_{anio}.csv")
ESTADO = {"disponible": False, "ultima_fecha": None}
_avisado = False
ACTIVO = os.environ.get("TENIS_CONTEXTO_ACTIVO", "1").strip().lower() not in {"0", "false", "no", "off"}
ANIOS = max(1, min(4, int(os.environ.get("TENIS_ANIOS", "2"))))
VENTANA_FORMA_DIAS = 120
MIN_FORMA = 5
MIN_SUPERFICIE = 8

_cache = U.CacheTTL(12 * 3600)
_cache_perfil = U.CacheTTL(6 * 3600)

_CLAY = ("roland garros", "french open", "madrid", "rome", "italian open", "charleston", "stuttgart", "rabat",
         "strasbourg", "bogota", "parma", "lausanne", "palermo", "prague", "budapest", "hamburg", "bucharest",
         "warsaw", "rio", "buenos aires", "bastad", "iasi", "cluj", "portoroz", "gdynia", "marrakech", "cali",
         "monterrey open", "contrexeville", "bad gastein", "belgrade", "lyon", "valencia", "palermo")
_GRASS = ("wimbledon", "berlin", "bad homburg", "eastbourne", "nottingham", "birmingham", "hertogenbosch",
          "mallorca", "queen's club", "ilkley", "surbiton")
_HARD = ("australian open", "us open", "indian wells", "miami", "cincinnati", "toronto", "montreal", "canadian",
         "dubai", "doha", "wuhan", "beijing", "china open", "tokyo", "pan pacific", "guadalajara", "ningbo", "seoul",
         "hong kong", "tianjin", "osaka", "linz", "moscow", "hobart", "adelaide", "sydney", "auckland", "brisbane",
         "abu dhabi", "austin", "san diego", "cleveland", "washington", "granby", "chennai", "jiujiang", "zhengzhou",
         "merida", "guangzhou", "shenzhen", "thailand", "hua hin", "monastir", "chicago", "cluj-napoca hard")


def superficie_torneo(nombre):
    """'Clay' / 'Grass' / 'Hard' segÃºn una tabla de torneos conocidos, o '' si no se sabe."""
    t = U.normalizar(nombre or "")
    for clave in _GRASS:
        if clave in t:
            return "Grass"
    for clave in _CLAY:
        if clave in t:
            return "Clay"
    for clave in _HARD:
        if clave in t:
            return "Hard"
    return ""


def _normalizar_superficie(texto):
    t = (texto or "").strip().lower()
    return {"clay": "Clay", "grass": "Grass", "hard": "Hard", "carpet": "Carpet"}.get(t, "")


def _cargar_anio(anio):
    hit, valor = _cache.get(anio)
    if hit:
        return valor
    texto = U.get_texto(BASE.format(anio=anio), "sackmann", timeout=25)
    if not texto:
        _cache.set(anio, [], ttl=30 * 60)  # archivo todavÃ­a inexistente o caÃ­da: se reintenta en 30 min
        return []
    filas = []
    try:
        for row in csv.DictReader(io.StringIO(texto)):
            fecha = str(row.get("tourney_date") or "")
            try:
                ts = int(datetime.strptime(fecha, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
            ganadora, perdedora = U.normalizar(row.get("winner_name")), U.normalizar(row.get("loser_name"))
            if ganadora and perdedora:
                filas.append((ts, _normalizar_superficie(row.get("surface")), ganadora, perdedora))
    except csv.Error:
        U.log(f"[tenis] CSV {anio} ilegible")
        return []
    U.log(f"[tenis] dataset {anio}: {len(filas)} partidos")
    _cache.set(anio, filas)
    return filas


def _indice():
    global _avisado
    hit, valor = _cache.get("indice")
    if hit:
        return valor
    indice = {}
    anio = datetime.now(timezone.utc).year
    for a in range(anio, anio - ANIOS, -1):
        for ts, superficie, ganadora, perdedora in _cargar_anio(a):
            indice.setdefault(ganadora, []).append((ts, superficie, True))
            indice.setdefault(perdedora, []).append((ts, superficie, False))
    for lista in indice.values():
        lista.sort(key=lambda x: x[0], reverse=True)
    ultima = max((ts for partidos in indice.values() for ts, _s, _g in partidos), default=0)
    vigente = bool(ultima and time.time() - ultima <= 45 * 86400)
    ESTADO.update(disponible=vigente, ultima_fecha=U.ts_a_iso_utc(ultima) if ultima else None)
    if not vigente:
        indice = {}
        if not _avisado:
            U.log("[tenis/contexto] no hay dataset reciente validado; forma/superficie deshabilitadas, no son señales neutrales")
            _avisado = True
    _cache.set("indice", indice, ttl=None if indice else 30 * 60)
    return indice


def _buscar(nombre, indice):
    objetivo = U.normalizar(nombre)
    if objetivo in indice:
        return indice[objetivo]
    if len(U.tokens_significativos(nombre)) < 2:
        return None  # un apellido suelto es ambiguo
    candidatos = [k for k in indice if U.nombres_coinciden(nombre, k) and len(U.tokens_significativos(k)) >= 2]
    return indice[candidatos[0]] if len(candidatos) == 1 else None


def perfil(nombre, superficie=""):
    """{forma_n, forma_wr, sup_n, sup_wr} de la jugadora, o None si no figura en el dataset."""
    clave = (U.normalizar(nombre), superficie)
    hit, valor = _cache_perfil.get(clave)
    if hit:
        return valor
    resultado = None
    partidos = _buscar(nombre, _indice())
    if partidos:
        limite = time.time() - VENTANA_FORMA_DIAS * 86400
        recientes = [g for ts, _s, g in partidos if ts >= limite][:10]
        en_superficie = [g for _ts, s, g in partidos if superficie and s == superficie]
        resultado = {
            "forma_n": len(recientes), "forma_wr": (sum(recientes) / len(recientes)) if recientes else None,
            "sup_n": len(en_superficie), "sup_wr": (sum(en_superficie) / len(en_superficie)) if en_superficie else None,
        }
    _cache_perfil.set(clave, resultado)
    return resultado


def evaluar_contexto(nombre_favorita, nombre_rival, torneo=""):
    """
    Contexto de la favorita POR RANKING frente a su rival:
    {"favorita_ventaja": -2..2, "detalles": [...], "superficie": "Clay"|...|""}. Sin datos suficientes: ventaja 0.
    """
    vacio = {"favorita_ventaja": 0, "detalles": [], "superficie": "", "disponible": False}
    if not ACTIVO:
        return vacio
    superficie = superficie_torneo(torneo)
    pf, pr = perfil(nombre_favorita, superficie), perfil(nombre_rival, superficie)
    vacio["superficie"] = superficie
    if not pf or not pr:
        return vacio

    ventaja, detalles = 0, []
    if pf["forma_n"] >= MIN_FORMA and pr["forma_n"] >= MIN_FORMA:
        if pf["forma_wr"] >= 0.70 and pr["forma_wr"] <= 0.40:
            ventaja += 1
            detalles.append(f"Forma tenis: favorita {round(pf['forma_wr'] * 100)}% vs rival {round(pr['forma_wr'] * 100)}% "
                            f"(Ãºltimos {pf['forma_n']}/{pr['forma_n']} partidos)")
        elif pf["forma_wr"] <= 0.40 and pr["forma_wr"] >= 0.70:
            ventaja -= 1
            detalles.append(f"Alerta de forma: la favorita viene {round(pf['forma_wr'] * 100)}% y la rival {round(pr['forma_wr'] * 100)}%")
    if superficie and pf["sup_n"] >= MIN_SUPERFICIE and pr["sup_n"] >= MIN_SUPERFICIE:
        brecha = pf["sup_wr"] - pr["sup_wr"]
        if brecha >= 0.25 and pf["sup_wr"] >= 0.55:
            ventaja += 1
            detalles.append(f"Superficie ({superficie}): favorita {round(pf['sup_wr'] * 100)}% vs rival {round(pr['sup_wr'] * 100)}%")
        elif brecha <= -0.20 or pf["sup_wr"] < 0.40:
            ventaja -= 1
            detalles.append(f"Alerta de superficie ({superficie}): favorita {round(pf['sup_wr'] * 100)}% vs rival {round(pr['sup_wr'] * 100)}%")
    return {"favorita_ventaja": max(-2, min(2, ventaja)), "detalles": detalles, "superficie": superficie, "disponible": bool(pf["forma_n"] >= MIN_FORMA and pr["forma_n"] >= MIN_FORMA)}