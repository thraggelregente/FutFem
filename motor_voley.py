"""Validación específica de resultados indoor al mejor de cinco.

El detector conserva sus umbrales. Los puntos por rally no se interpretan como
sets; tampoco sirven los walkovers, empates o partidos incompletos.
"""


def historial_sets(partidos):
    salida=[]
    for p in partidos or []:
        a,b=p.get('puntos_local'),p.get('puntos_visita')
        if any(type(v) is not int or v < 0 for v in (a,b)):
            continue
        if max(a,b)!=3 or min(a,b)>2:
            continue
        if p.get('estado_resultado') in ('walkover','retired','abandoned','cancelled'):
            continue
        salida.append(p)
    return salida
