"""
fuente_flashscore.py
Scraper de FlashScore (https://www.flashscore.com/).

FlashScore no tiene API oficial. Se scrapea el HTML con requests + BeautifulSoup.

Requiere:
- pip install beautifulsoup4 lxml

Deportes soportados:
- Football, Tennis, Basketball, Volleyball, Handball, etc.
"""

import os
import re

import utilidades as U

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

HEADERS_FLASHSCORE = dict(U.HEADERS_NAVEGADOR, Referer="https://www.flashscore.com/")

_cache = U.CacheTTL(15 * 60)


def obtener_eventos(deporte_interno, fecha=None):
    """
    TODO: Implementar scraping de FlashScore.
    Devuelve lista de eventos en formato interno.
    """
    if BeautifulSoup is None:
        U.log("[flashscore] beautifulsoup4 no instalado")
        return []
    
    # TODO: Implementar lógica real aquí
    return []


def es_femenino(evento):
    """TODO: Verificar que la liga sea femenina."""
    return True