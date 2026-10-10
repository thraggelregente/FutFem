"""
tracker_cuotas_smart.py
Monitor de mercado (The Odds API):
- Busca el evento por equipos locales Y visitantes (no por un solo nombre) dentro de los
  sport_keys FEMENINOS activos (WNBA, WTA, NWSL, etc.), en vez de /sports/upcoming.
- Compara Pinnacle contra la mejor cuota y detecta cuotas colapsadas (<= 1.08).
- Guarda la primera cuota que vio el radar para cada evento y detecta desplomes
  (calcular_desplome ahora sí se usa). Es "primera lectura del radar", no la apertura real.

Costo en créditos: 1 región x 1 mercado = 1 crédito por sport_key consultado, con cache
de 20 minutos. El plan gratuito tiene 500 créditos/mes: ajustá ODDS_MAX_SPORT_KEYS si hace falta.
"""

import os
from datetime import datetime, timezone

import utilidades as U

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
BASE = "https://api.the-odds-api.com/v4"
MAX_SPORT_KEYS = int(os.environ.get("ODDS_MAX_SPORT_KEYS", "4"))
ARCHIVO_HISTORIAL = "historial_cuotas.json"

LOCAL = "Local"

# Prefijo del sport_key de The Odds API según el deporte del radar
_PREFIJOS = {
    "Soccer": "soccer_",
    "Basketball": "basketball_",
    "Tennis": "tennis_",
    "Ice Hockey": "icehockey_",
    "Handball": "handball_",
    "Volleyball": "volleyball_",
    "Rugby": "rugbyunion_",
    "Cricket": "cricket_",
    "Field Hockey": "hockey_",
}

_MARCAS_FEMENINAS = ("women", "wnba", "wta", "nwsl", "ladies", "_w_", "feminin")

_cache_sports = U.CacheTTL(6 * 3600)
_cache_odds = U.CacheTTL(20 * 60)
_historial = None


def calcular_desplome(cuota_apertura, cuota_actual):
    """Caída porcentual de la cuota. >= 20% en un favorito suele indicar dinero fuerte."""
    if not cuota_apertura or not cuota_actual or cuota_apertura <= 1.0:
        return 0.0, False
    caida_pct = ((cuota_apertura - cuota_actual) / cuota_apertura) * 100
    return round(caida_pct, 1), caida_pct >= 20.0


def _sport_keys_femeninos(deporte):
    prefijo = _PREFIJOS.get(deporte)
    if not prefijo:
        return []

    hit, todas = _cache_sports.get("todas")
    if not hit:
        data = U.get_json(f"{BASE}/sports", "odds_api", params={"apiKey": ODDS_API_KEY}, timeout=10)
        if not isinstance(data, list):
            return []
        todas = []
        for s in data:
            if not s.get("active") or s.get("has_outrights"):
                continue
            texto = f"{s.get('key', '')} {s.get('title', '')} {s.get('description', '')}".lower()
            if any(m in texto for m in _MARCAS_FEMENINAS):
                todas.append(s["key"])
        _cache_sports.set("todas", todas)

    return [k for k in todas if k.startswith(prefijo)][:MAX_SPORT_KEYS]


def _eventos_de(sport_key):
    hit, eventos = _cache_odds.get(sport_key)
    if hit:
        return eventos

    info = {}
    data = U.get_json(
        f"{BASE}/sports/{sport_key}/odds", "odds_api",
        params={"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"},
        timeout=10, info=info,
    )
    restantes = (info.get("headers") or {}).get("x-requests-remaining")
    if restantes is not None:
        U.log(f"[odds_api] créditos restantes: {restantes}")
    if isinstance(data, list):
        _cache_odds.set(sport_key, data)
        return data
    return []


def _cargar_historial():
    global _historial
    if _historial is None:
        crudo = U.cargar_json(ARCHIVO_HISTORIAL, {})
        _historial = crudo if isinstance(crudo, dict) else {}
        _historial = {k: v for k, v in _historial.items() if isinstance(v, dict)}
        limite = U.podar_por_antiguedad({k: v.get("ts", "") for k, v in _historial.items()}, 3)
        _historial = {k: v for k, v in _historial.items() if k in limite}
    return _historial


def _registrar_cuota(event_id, nombre_fav, cuota):
    """Devuelve la cuota de la primera lectura del radar (y la guarda si es nueva)."""
    historial = _cargar_historial()
    clave = f"{event_id}|{U.normalizar(nombre_fav)}"
    previa = historial.get(clave)
    if previa:
        return previa.get("cuota"), previa.get("ts")
    historial[clave] = {"cuota": cuota, "ts": datetime.now(timezone.utc).isoformat()}
    U.guardar_json(ARCHIVO_HISTORIAL, historial)
    return None, None


def analizar_mercado_evento(equipo_local, equipo_visita, favorito=LOCAL, deporte="Soccer"):
    """
    Cuota del FAVORITO (local o visitante). Devuelve {'disponible': bool, 'resumen': str, ...}.
    """
    if not ODDS_API_KEY:
        return {"disponible": False, "mensaje": "Monitor de cuotas inactivo (falta ODDS_API_KEY)"}

    keys = _sport_keys_femeninos(deporte)
    if not keys:
        return {"disponible": False, "mensaje": "Sin cobertura de cuotas para este deporte/torneo femenino"}

    nombre_fav = equipo_local if favorito == LOCAL else equipo_visita

    for sport_key in keys:
        for ev in _eventos_de(sport_key):
            h, a = ev.get("home_team", ""), ev.get("away_team", "")
            directo = U.nombres_coinciden(equipo_local, h) and U.nombres_coinciden(equipo_visita, a)
            cruzado = U.nombres_coinciden(equipo_local, a) and U.nombres_coinciden(equipo_visita, h)
            if not (directo or cruzado):
                continue

            cuotas = []  # (casa, precio)
            pinnacle = None
            for b in ev.get("bookmakers", []):
                for m in b.get("markets", []):
                    if m.get("key") != "h2h":
                        continue
                    for out in m.get("outcomes", []):
                        if U.nombres_coinciden(nombre_fav, out.get("name", "")):
                            precio = out.get("price")
                            if not precio:
                                continue
                            cuotas.append((b.get("title") or b.get("key"), precio))
                            if "pinnacle" in str(b.get("key", "")).lower():
                                pinnacle = precio

            if not cuotas:
                continue

            mejor_casa, cuota_max = max(cuotas, key=lambda x: x[1])
            cuota_ref = pinnacle or min(p for _, p in cuotas)
            desfase = round((cuota_max - cuota_ref) / cuota_ref * 100, 1) if cuota_ref > 1.0 else 0.0

            primera, _ = _registrar_cuota(ev.get("id", f"{h}-{a}"), nombre_fav, cuota_max)
            caida_pct, es_desplome = calcular_desplome(primera, cuota_max) if primera else (0.0, False)

            partes = [f"Pinnacle/base @{cuota_ref} | Mejor cuota @{cuota_max} ({mejor_casa})"]
            if desfase >= 15.0:
                partes.append(f"⚠️ Desfase de valor entre casas: +{desfase}%")
            if cuota_max <= 1.08:
                partes.append("Cuota colapsada: conviene esperar LIVE o hándicap alto")
            if es_desplome:
                partes.append(f"📉 Cayó {caida_pct}% desde la primera lectura del radar")

            return {
                "disponible": True,
                "cuota_pinnacle": pinnacle,
                "mejor_cuota_mercado": cuota_max,
                "desfase_pct": desfase,
                "alerta_smart_money": desfase >= 18.0 or es_desplome,
                "resumen": " | ".join(partes),
            }

    return {"disponible": False, "mensaje": "Evento sin liquidez o fuera de las casas comerciales"}



