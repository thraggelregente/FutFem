"""
fuente_api_football.py
Fuente de datos de API-Football (https://www.api-football.com/).

Plan gratuito: 100 requests/día.
Requiere API key: variable de entorno API_FOOTBALL_KEY.

Documentación: https://www.api-football.com/documentation-v3

Deportes soportados:
- Football (fútbol): decenas de ligas femeninas.
- Basketball, Volleyball, Handball, etc. (según el plan).

La API tiene endpoints específicos para ligas femeninas.
"""

import os

import utilidades as U

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_HOST = "v3.football.api-sports.io"
API_FOOTBALL_HOST_BASKET = "v1.basketball.api-sports.io"
API_FOOTBALL_HOST_VOLLEY = "v1.volleyball.api-sports.io"
API_FOOTBALL_HOST_HANDBALL = "v1.handball.api-sports.io"

_cache = U.CacheTTL(30 * 60)


def _headers():
    return {
        "x-rapidapi-key": API_FOOTBALL_KEY,
        "x-rapidapi-host": API_FOOTBALL_HOST,
    }


def obtener_eventos(deporte_interno, fecha=None):
    """
    TODO: Implementar consulta a API-Football.
    Devuelve lista de eventos en formato interno (igual que fuente_espn).
    
    Formato interno:
    {
        "id": "apifootball_XXXXX",
        "deporte": "Soccer",
        "torneo": "Liga F (España)",
        "local": {"id": ..., "nombre": ..., "record": ..., "ranking": ...},
        "visita": {"id": ..., "nombre": ..., "record": ..., "ranking": ...},
        "horario": "10/10 15:00 hs (ARG)",
        "estado": "Programado",
        "tipo_estado": "pre",  # pre | in | post
        "startTimestamp": 1234567890,
        "fuente": "api_football",
    }
    """
    if not API_FOOTBALL_KEY:
        return []
    
    # TODO: Implementar lógica real aquí
    return []


def es_femenino(evento):
    """TODO: Verificar que la liga sea femenina."""
    return True