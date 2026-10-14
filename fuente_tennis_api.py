"""Tennis API opcional: factual femenino; 50 solicitudes/24 h compartidas.

No consulta rutas de predicción ni mercados. Conserva sólo campos permitidos.
La profundidad ITF y la autorización se validarán con la suscripción del operador.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone
import utilidades as U
from fuentes_publicas import PresupuestoVentana

FUENTE='tennis_api'
KEY=os.environ.get('TENNIS_API_RAPIDAPI_KEY','').strip()
HOST='tennis-api-atp-wta-itf.p.rapidapi.com'
presupuesto=PresupuestoVentana('tennis_api',50)
_cache=U.CachePersistente('tennis_api_factual_v1',6*3600,max_items=128)
_ritmo=U.RitmoPedidos(4,minimo_segundos=.3)
_pause=0


def disponible():
    return bool(KEY)


def factual(raw):
    """Lista permitida ANTES de cachear: se eliminan cuotas y links a mercados."""
    fields=('id','matchId','date','startTime','player1Id','player2Id','tournamentId','roundId','seed1','seed2','live','result','result_type','match_winner')
    row={key:raw.get(key) for key in fields if key in raw}
    for player in ('player1','player2'):
        value=raw.get(player) or {}
        if isinstance(value,dict):
            row[player]={k:value.get(k) for k in ('id','name','countryAcr')}
    value=raw.get('tournament') or {}
    if isinstance(value,dict):
        row['tournament']={k:value.get(k) for k in ('id','name','date','courtId','rankId','countryAcr')}
        row['tournament']['court']={k:(value.get('court') or {}).get(k) for k in ('id','name')}
    return row


def _get(path, params, ttl):
    global _pause
    import planificador_datos as P
    hit, value=_cache.get((path,params))
    if hit:
        return value
    if not disponible() or time.time()<_pause or not P.actual.permitido(FUENTE) or not presupuesto.puede_gastar():
        return None
    _ritmo.esperar()
    presupuesto.registrar()
    info={}
    response=U.get_json('https://'+HOST+path,FUENTE,headers={'X-RapidAPI-Key':KEY,'X-RapidAPI-Host':HOST},
                        params=params,info=info,reintentar=False)
    if info.get('status') in (401,403,429):
        _pause=time.time()+86400
    headers={k.lower():v for k,v in (info.get('headers') or {}).items()}
    try:
        if int(headers.get('x-ratelimit-requests-remaining','1'))<=0:
            _pause=time.time()+86400
    except (TypeError,ValueError):
        pass
    if not isinstance(response,dict) or not isinstance(response.get('data'),list):
        _cache.set((path,params),None,ttl=3600)
        return None
    data={'data':[factual(row) for row in response['data'] if isinstance(row,dict)],
          'hasNextPage':response.get('hasNextPage')}
    _cache.set((path,params),data,ttl=ttl)
    return data


def _pages(family,dia,max_pages=4):
    rows=[]
    for page in range(1,max_pages+1):
        params={'filter':'PlayerGroup:singles','pageSize':500,'pageNo':page}
        if family=='fixtures':
            params['include']='round,tournament,tournament.court'
        data=_get('/tennis/v2/wta/'+family+'/'+dia,params,1800 if family=='results' else 6*3600)
        if not data:
            break
        rows.extend(data['data'])
        if data.get('hasNextPage') is False or not data['data']:
            break
        if page==max_pages or data.get('hasNextPage') is not True:
            import cobertura_radar
            cobertura_radar.actual.truncado(FUENTE,'Tennis')
            break
    return rows


def normalizar(raw, now=None):
    now=time.time() if now is None else now
    names=[(raw.get(p) or {}).get('name') for p in ('player1','player2')]
    ids=[(raw.get(p) or {}).get('id') for p in ('player1','player2')]
    if not all(isinstance(n,str) and U.participante_definido(n) and '/' not in n for n in names) or not all(ids) or ids[0]==ids[1]:
        return None
    stamp=raw.get('startTime') or raw.get('date')
    if not isinstance(stamp,str) or not re.search(r'T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$',stamp):
        return None
    when=U._parsear_iso(stamp)
    torneo=raw.get('tournament') or {}
    if not when or not now<when.timestamp()<=now+86400 or raw.get('live') or raw.get('result') or not raw.get('id') or not torneo.get('id'):
        return None
    if not torneo.get('name') or not torneo.get('date'):
        return None
    start=U._parsear_iso(torneo['date'])
    if not start or abs(when.timestamp()-start.timestamp())>21*86400:
        return None  # edición incoherente o dato histórico
    players=[]
    for i,(pid,name) in enumerate(zip(ids,names),1):
        entry=raw.get('seed'+str(i))
        players.append({'id':'tapi:'+str(pid),'nombre':name,'tennis_api_id':pid,
                        'entry':entry if entry in ('WC','Q','PR') else None, 'entry_fuente':'Tennis API (tercero)'})
    return {'id':'tapi_fixture_'+str(raw['id']), 'fuente':FUENTE,'deporte':'Tennis','femenino_seguro':True,
            'torneo':torneo['name'], 'contexto_competicion':'tapi:'+str(torneo['id']),
            'season_ref':start.year,'round_ref':raw.get('roundId'),'tipo_estado':'pre',
            'startTimestamp':int(when.timestamp()),'horario':U.formatear_hora_arg(when.timestamp()),
            'local':players[0],'visita':players[1], 'superficie':(torneo.get('court') or {}).get('name')}


def obtener_eventos(deporte):
    if deporte!='Tennis' or not disponible():
        return []
    rows=[]
    for delta in (0,1):
        dia=(datetime.now(timezone.utc)+timedelta(days=delta)).date().isoformat()
        rows.extend(p for raw in _pages('fixtures',dia) if (p:=normalizar(raw)))
    return rows


def resultados_evaluacion(evento):
    if evento.get('deporte')!='Tennis' or not disponible():
        return []
    observations=[o for o in evento.get('_observaciones') or [evento] if o.get('fuente')==FUENTE]
    if not observations:
        return []
    dia=datetime.fromtimestamp(evento['startTimestamp'],timezone.utc).date().isoformat()
    output=[]
    from auditoria_decisiones import contexto
    for raw in _pages('results',dia):
        names=[(raw.get(p) or {}).get('name') for p in ('player1','player2')]
        if not all(isinstance(n,str) and '/' not in n for n in names):
            continue
        torneo=raw.get('tournamentId') or (raw.get('tournament') or {}).get('id')
        candidates=[o for o in observations if o.get('contexto_competicion')=='tapi:'+str(torneo)
            and o.get('round_ref')==raw.get('roundId') and raw.get('roundId') is not None
            and {U.firma_equipo(n) for n in names}=={U.firma_equipo((o.get(l) or {}).get('nombre','')) for l in ('local','visita')}]
        if len(candidates)!=1:
            continue
        state={'completed':'normal','retired':'retirement','walkover':'walkover','default':'walkover'}.get(raw.get('result_type'))
        if not state:
            continue
        sets=[[int(a),int(b)] for a,b in re.findall(r'(\d+)(?:\(\d+\))?-(\d+)(?:\(\d+\))?',raw.get('result') or '')]
        if state=='normal' and (len(sets) not in (2,3) or sum(a>b for a,b in sets)!=2):
            continue
        obs=candidates[0]
        output.append(dict(contexto(obs),source=FUENTE,provider_id=obs['id'],archive_id=raw.get('id'),
            participants=[U.firma_equipo(n) for n in names],participant_names=names,
            winner=U.firma_equipo(names[0]),status=state,sets=sets,score=None,original_score=raw.get('result'),
            kickoff_utc=obs['startTimestamp'],kickoff_precision='exact',verified_at=time.time()))
    return output
