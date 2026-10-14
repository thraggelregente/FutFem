"""Vóley femenino LVF oficial: contexto nacional, sin clave privada."""
import os
from voley_oficial import Oficial, cargar_lvf
FUENTE='lvf'
ACTIVO=os.environ.get('LVF_ACTIVO','1')!='0'
oficial=Oficial(FUENTE)
_cache=oficial.cache
presupuesto=oficial.cliente.presupuesto

def disponible():return ACTIVO

def obtener_eventos(deporte):
    if deporte=='Volleyball' and disponible():
        cargar_lvf(oficial)
    return [] # Este conector complementa datos; no inventa fixtures sin hora verificada.

def tabla_partido(ev):return oficial.tabla_para_evento(ev)

def historial_equipo(ev,lado):return oficial.historial_para_evento(ev,lado)

def estado_contexto():return dict(oficial.status)

def resultados_evaluacion(ev):return oficial.resultados_para_evento(ev)
