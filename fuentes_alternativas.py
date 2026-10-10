"""Fuentes alternativas de tenis.

La API pública del calendario ITF devuelve 403/404 en el despliegue informado. No
se intenta sortear WAF, autenticación ni controles del sitio. El módulo permanece
como punto de integración para una API autorizada o feed oficial documentado.
"""

import os

import utilidades as U

ITF_API_KEY = (os.environ.get("ITF_API_KEY") or "").strip()


def disponible():
    """No hay un endpoint ITF autorizado configurado; no fingir disponibilidad."""
    return False


def obtener_mismatches_itf():
    U.log(
        "[itf] fuente deshabilitada: el calendario oficial rechazó requests (403/404); "
        "no se intenta eludir el WAF. WTA se obtiene desde ESPN hasta configurar un feed autorizado."
    )
    return []
