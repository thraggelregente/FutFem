"""Contexto por deporte y selección descriptiva de mercados, sin cuotas/probabilidades.

Los umbrales de esta capa son reglas de elegibilidad, no una calibración predictiva.
No modifica el puntaje del detector ni transforma frecuencias históricas en certezas.
"""
import math
from datetime import datetime, timezone

VERSION = 'sport-context-v1'
PERFILES = {
    'Soccer': ('goles', 'resultado en tiempo reglamentario; distinguir copas y prórroga'),
    'Basketball': ('puntos', 'margen de puntos; diferenciar ritmo, plantel y prórroga'),
    'Volleyball': ('sets', 'sets ganados/perdidos y victorias por dos o más sets'),
    'Handball': ('goles', 'margen de goles y rendimiento reciente'),
    'Ice Hockey': ('goles', 'distinguir tiempo reglamentario, prórroga y penales'),
    'Rugby': ('puntos', 'misma modalidad: XV, seven y otras no se mezclan'),
    'Softball': ('carreras', 'carreras; faltan lanzadoras para un modelo completo'),
    'Lacrosse': ('goles', 'misma modalidad y categoría de competición'),
    'Field Hockey': ('goles', 'tiempo reglamentario y penales separados'),
    'Tennis': ('sets y juegos', 'superficie, rivales comparables y experiencia documentada'),
    'Cricket': ('runs o wickets', 'T20 y ODI separados; no sumar unidades diferentes'),
}


def _wilson_inferior(k, n):
    z = 1.96
    return (k/n + z*z/(2*n) - z*math.sqrt(k/n*(1-k/n)/n + z*z/(4*n*n)))/(1+z*z/n)


def _muestra(rows, pid, ahora, deporte):
    if pid is None:
        return []
    validos = {}
    for p in rows or []:
        try:
            ts = datetime.fromisoformat(str(p['fecha']).replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if not 0 < ahora-ts.timestamp() <= 90*86400:
                continue
            a, b = str(p['id_local']), str(p['id_visita'])
            x, y = p['puntos_local'], p['puntos_visita']
            if str(pid) not in (a, b) or a == b or any(type(v) is not int or v < 0 for v in (x, y)):
                continue
            # Indoor senior al mejor de cinco; un marcador en puntos no es sets.
            if deporte == 'Volleyball' and not (max(x,y) == 3 and min(x,y) <= 2):
                continue
            if p.get('estado_resultado') in ('retired', 'walkover', 'abandoned', 'cancelled'):
                continue
            key = (ts.isoformat(), tuple(sorted((a,b))))
            score = (x,y) if a < b else (y,x)
            if key in validos and validos[key][2] != score:
                return []  # resultados contradictorios de un mismo partido
            validos[key] = (ts.timestamp(), x-y if str(pid)==a else y-x, score)
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return [v[1] for v in sorted(validos.values(), reverse=True)[:10]]


def equipos(ev, resultado, local, visita, ahora):
    sport = ev.get('deporte')
    unidad, foco = PERFILES.get(sport, ('unidades', 'contexto insuficiente'))
    samples = [_muestra(rows, (ev.get(side) or {}).get('id'), ahora, sport)
               for rows,side in ((local,'local'),(visita,'visita'))]
    detalle, faltantes = [], []
    for side, sample in zip(('local','visita'), samples):
        name = (ev.get(side) or {}).get('nombre', side)
        if sample:
            detalle.append(f"{name}: {sum(v>0 for v in sample)}/{len(sample)} victorias; "
                           f"margen medio observado {sum(sample)/len(sample):+.1f} {unidad} (hasta 10 partidos, 90 días).")
        if len(sample) < 4:
            faltantes.append(f"Historial reciente suficiente de {name}: {len(sample)}/4 partidos válidos.")
    out = {'version': VERSION, 'perfil': foco, 'evidencia': detalle, 'faltantes': faltantes,
           'selecciones': [], 'estado': 'sin_recomendacion', 'criterio': ''}
    if not resultado.get('hay_mismatch'):
        out['criterio'] = 'Las señales no alcanzan el umbral del detector.'
        return out
    fav = 0 if resultado.get('favorito') == 'Local' else 1
    sf, sr = samples[fav], samples[1-fav]
    familias = set(resultado.get('familias_senales') or [])
    historial = any(s.get('side') == resultado.get('favorito') and s.get('family') == 'historial'
                    and s.get('effective_points',0) > 0 for s in resultado.get('signals',[]))
    if min(map(len,samples)) < 4 or not historial or len(familias) < 2 or resultado.get('calidad_datos') != 'Suficiente':
        out['criterio'] = 'Falta historial reciente o acompañamiento de otra familia de señales para recomendar un mercado.'
        return out
    name = (ev['local'] if fav == 0 else ev['visita'])['nombre']
    if sport not in ('Volleyball', 'Basketball', 'Handball'):
        out['criterio'] = f"Ventaja deportiva hacia {name}; falta verificar formato y reglas del mercado. {foco}."
        return out
    if sum(x>0 for x in sf)/len(sf) < .75 or sum(x<0 for x in sr)/len(sr) < .75:
        out['criterio'] = 'Los resultados observados no acompañan suficientemente la selección del mercado.'
        return out
    out['selecciones'].append({'mercado': 'Ganador del partido', 'seleccion': name,
                              'motivo': 'Forma reciente y otra familia de señales coinciden; criterio deportivo sin calibración predictiva.'})
    out['estado'] = 'orientacion_deportiva'
    out['criterio'] = 'Son mercados para evaluar con estas evidencias; no se calcula rentabilidad ni probabilidad de acierto.'
    if sport in ('Basketball','Handball'):
        out['criterio'] += ' Verificar en la casa si el mercado incluye prórroga: el historial no separa siempre esos períodos.'
    if sport == 'Volleyball':
        # Exigir evidencia por separado: no tratar dos muestras de rivales distintos como una sola.
        kf, kr = sum(x>=2 for x in sf), sum(x<=-2 for x in sr)
        if min(len(sf),len(sr)) >= 8 and min(_wilson_inferior(kf,len(sf)), _wilson_inferior(kr,len(sr))) > .5:
            out['selecciones'].append({'mercado': 'Hándicap de sets −1,5', 'seleccion': name,
                'motivo': f"Ganó por al menos dos sets en {kf}/{len(sf)}; la rival perdió por ese margen en {kr}/{len(sr)}. "
                          'Gana con 3–0 o 3–1 en un partido al mejor de cinco; no se propone resultado exacto.'})
    return out


def tenis(resultado, comparacion, superficie, h2h, comunes, faltantes):
    out = {'version': VERSION, 'perfil': PERFILES['Tennis'][1], 'evidencia': [],
           'faltantes': list(faltantes), 'selecciones': [], 'estado': 'sin_recomendacion',
           'criterio': 'La brecha de ranking permite seguir el partido; todavía falta confirmar la superioridad con resultados comparables.'}
    if resultado.get('tipo','').startswith('CANDIDATO'):
        return out
    # Forma y superficie comparten partidos: cuentan como una sola familia.
    apoyo = bool((comparacion and comparacion['brecha'] >= .25) or (superficie and superficie['brecha'] >= .25))
    respaldo = bool((h2h and h2h['favor'] >= 2 and h2h['contra'] == 0) or (comunes and comunes['favor'] >= 2 and comunes['contra'] == 0))
    if apoyo and respaldo:
        out.update(estado='orientacion_deportiva', criterio='Resultados comparables y enfrentamientos acompañan el ranking; sin probabilidad calibrada.')
        out['selecciones'] = [{'mercado':'Ganadora del partido', 'seleccion_lado':resultado['favorito'],
            'motivo':'Forma comparable y H2H o rivales comunes respaldan la misma jugadora.'}]
    else:
        out['criterio'] = 'La ventaja tiene contexto deportivo, pero falta acompañamiento suficiente para seleccionar un mercado.'
    # Ni el ranking ni el total de juegos justifican un 2–0 o un hándicap de juegos.
    return out
