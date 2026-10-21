"""Vóley femenino LNV oficial: contexto nacional, sin clave privada."""
import os
from voley_oficial import Oficial, cargar_lnv, completar_lnv
FUENTE='lnv'
ACTIVO=os.environ.get('LNV_ACTIVO','1')!='0'
oficial=Oficial(FUENTE)
_cache=oficial.cache
presupuesto=oficial.cliente.presupuesto

def disponible():return ACTIVO

def obtener_eventos(deporte):
    if deporte=='Volleyball' and disponible():
        cargar_lnv(oficial)
    return [] # Este conector complementa datos; no inventa fixtures sin hora verificada.

def tabla_partido(ev):return oficial.tabla_para_evento(ev)

def historial_equipo(ev,lado):
    if not disponible() or not oficial.tabla_para_evento(ev)[0]:return []
    if oficial.edicion and hasattr(oficial,'_lnv_pid'):
        completar_lnv(oficial,oficial.edicion.split(':')[-1],oficial._lnv_pid,
                      equipos={oficial.resolver(ev[s]['nombre']) for s in ('local','visita')})
    return oficial.historial_para_evento(ev,lado)

def iniciar_ciclo():oficial.details_cycle=0

def estado_contexto():return dict(oficial.status)

def resultados_evaluacion(ev):return oficial.resultados_para_evento(ev)
