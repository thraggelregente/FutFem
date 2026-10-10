"""
fuente_thesportsdb.py
Fuente de datos de TheSportsDB (https://www.thesportsdb.com/).

API gratuita (con key "3" para testing).
Documentación: https://www.thesportsdb.com/free_sports_api

Deportes soportados:
- Soccer, Basketball, Motorsport, etc.
"""

import os

import utilidades as U

THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "3")  # "3" es la key de testing gratuita
THESPORTSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_KEY}"

_cache = U.CacheTTL(30 * 60)


def obtener_eventos(deporte_interno, fecha=None):
    """
    TODO: Implementar consulta a TheSportsDB.
    Devuelve lista de eventos en formato interno.
    """
    # TODO: Implementar lógica real aquí
    return []


def es_femenino(evento):
    """TODO: Verificar que la liga sea femenina."""
    return True