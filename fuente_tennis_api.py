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
_context_calls=0
_context_budget=PresupuestoVentana('tennis_api_contexto',28)
_metrics={'profiles_verified':0,'histories_verified':0,'rank_fallbacks':0,'rank_conflicts':0}


def disponible():
    return bool(KEY)


def factual(raw):
    """Lista permitida ANTES de cachear: se eliminan cuotas y links a mercados."""
    fields=('id','matchId','date','startTime','player1Id','player2Id','tournamentId','roundId','seed1','seed2','live','result','result_type','match_winner','best_of')
    row={key:raw.get(key) for key in fields if key in raw}
    for player in ('player1','player2'):
        value=raw.get(player) or {}
        if isinstance(value,dict):
            row[player]={k:value.get(k) for k in ('id','name','countryAcr')}
    value=raw.get('tournament') or {}
    if isinstance(value,dict):
        row['tournament']={k:value.get(k) for k in ('id','name','date','courtId','rankId','countryAcr')}
        court=value.get('court')
        row['tournament']['court']={k:court.get(k) for k in ('id','name')} if isinstance(court,dict) else {}
    return row


def _get(path, params, ttl, profile=False, context=False):
    global _pause, _context_calls
    import planificador_datos as P
    hit, value=_cache.get((path,params))
    if hit:
        return value
    if not disponible() or time.time()<_pause or not P.actual.permitido(FUENTE) or not presupuesto.puede_gastar():
        return None
    if context and (_context_calls >= 6 or presupuesto.restantes() <= 8 or not _context_budget.puede_gastar()):
        return None
    _ritmo.esperar()
    if context:
        _context_calls += 1
        _context_budget.registrar()
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
    payload=response.get('data') if isinstance(response,dict) else None
    if profile and isinstance(payload,dict):
        fields=('id','name','currentRank','rankingDate','playerStatus','bestRank','curRank')
        data={'data':{key:_profile_field(key,payload.get(key)) for key in fields}, 'fetched_at':time.time()}
    elif not profile and isinstance(payload,list):
        data={'data':[factual(row) for row in payload if isinstance(row,dict)],
              'hasNextPage':response.get('hasNextPage'),'fetched_at':time.time()}
    else:
        _cache.set((path,params),None,ttl=3600)
        return None
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


def _profile_field(key,value):
    if key in ('curRank','bestRank'):
        return {k:value.get(k) for k in ('rank','position','date')} if isinstance(value,dict) else None
    return value if value is None or isinstance(value,(str,int,float)) and not isinstance(value,bool) else None


def iniciar_ciclo():
    global _context_calls
    _context_calls=0
    for key in _metrics:
        _metrics[key]=0


def _pid(jugadora):
    pid=jugadora.get('tennis_api_id')
    return str(pid) if str(pid or '').isdigit() and int(pid)>0 else None


def perfil_basico(jugadora):
    pid=_pid(jugadora)
    if not pid:
        return None
    data=_get('/tennis/v2/wta/player/profile/'+pid,{'include':'ranking'},86400,profile=True,context=True)
    raw=(data or {}).get('data')
    if not isinstance(raw,dict) or str(raw.get('id'))!=pid or U.firma_equipo(raw.get('name',''))!=U.firma_equipo(jugadora.get('nombre','')):
        return None
    rank=raw.get('currentRank')
    fecha=U._parsear_iso(str(raw.get('rankingDate') or ''))
    vigente=bool(fecha and 0<=time.time()-fecha.timestamp()<=14*86400)
    best=raw.get('bestRank') or {}
    mejor=best.get('rank') or best.get('position')
    _metrics['profiles_verified']+=1
    if vigente and isinstance(rank,int) and jugadora.get('ranking') and str(jugadora.get('ranking_fecha'))[:10]==fecha.date().isoformat() and rank!=jugadora['ranking']:
        jugadora['ranking_conflicto']=True
    return {'id':pid,'nombre':raw['name'],'ranking':rank if vigente and isinstance(rank,int) and not isinstance(rank,bool) and rank>0 else None,
            'ranking_fecha':fecha.date().isoformat() if vigente else None,
            'mejor_ranking':mejor if isinstance(mejor,int) and mejor>0 else None,
            'estado':raw.get('playerStatus'),'actualizado_utc':(data or {}).get('fetched_at')}


def enriquecer_rankings(eventos):
    """IDs sólo de observaciones con nombres exactos; prioridad para datos ausentes."""
    pendientes=[]
    for ev in eventos:
        if ev.get('deporte')!='Tennis':
            continue
        for lado in ('local','visita'):
            jugador=ev.get(lado) or {}
            ids=set()
            for obs in ev.get('_observaciones') or [ev]:
                if obs.get('fuente')!=FUENTE:
                    continue
                for olado in ('local','visita'):
                    other=obs.get(olado) or {}
                    if U.firma_equipo(other.get('nombre',''))==U.firma_equipo(jugador.get('nombre','')) and _pid(other):
                        ids.add(_pid(other))
            if len(ids)!=1:
                continue
            jugador['tennis_api_id']=next(iter(ids))
            pendientes.append((bool(jugador.get('ranking')),ev.get('startTimestamp',0),jugador))
    for _,_,jugador in sorted(pendientes,key=lambda t:(t[0],t[1])):
        # Conservar ranking oficial; comprobar también perfiles ya cacheados sin gasto nuevo.
        pid=_pid(jugador)
        cached=_cache.get(('/tennis/v2/wta/player/profile/'+pid,{'include':'ranking'}))[0]
        if (_context_calls >= 2 or jugador.get('ranking')) and not cached:
            continue
        perfil=perfil_basico(jugador)
        if not perfil or not perfil['ranking']:
            continue
        jugador['ranking_tennis_api_observado']=perfil
        if not jugador.get('ranking'):
            jugador.update(ranking=perfil['ranking'],ranking_fecha=perfil['ranking_fecha'],ranking_fuente='Tennis API; ranking fechado')
            _metrics['rank_fallbacks']+=1
        elif str(jugador.get('ranking_fecha'))[:10]==perfil['ranking_fecha'] and jugador['ranking']!=perfil['ranking']:
            jugador['ranking_conflicto']=True
            _metrics['rank_conflicts']+=1


def normalizar_historial(raw,pid,ahora=None):
    ahora=time.time() if ahora is None else ahora
    a,b=raw.get('player1') or {},raw.get('player2') or {}
    ids=[str(a.get('id')),str(b.get('id'))]
    if str(pid) not in ids or ids[0]==ids[1] or not all(U.participante_definido(p.get('name','')) and '/' not in p.get('name','') for p in (a,b)):
        return None
    if raw.get('result_type')!='completed':
        return None
    fecha=U._parsear_iso(str(raw.get('date') or ''))
    if not fecha or not ahora-2*366*86400<=fecha.timestamp()<ahora or fecha.year<2016:
        return None
    sets=[[int(a),int(b)] for a,b in re.findall(r'(\d+)(?:\(\d+\))?\s*-\s*(\d+)(?:\(\d+\))?',str(raw.get('result') or ''))]
    def valid(a,b):
        return (a==6 and b<=4) or (a==7 and b in (5,6)) or (a==b+2 and a>7) or (b==6 and a<=4) or (b==7 and a in (5,6)) or (b==a+2 and b>7)
    if len(sets) not in (2,3) or not all(valid(a,b) for a,b in sets) or sum(a>b for a,b in sets)!=2:
        return None
    if raw.get('match_winner') is not None and str(raw['match_winner'])!=ids[0]:
        return None
    gano=str(pid)==ids[0]
    gf,gc=sum(a for a,b in sets),sum(b for a,b in sets)
    torneo=raw.get('tournament') or {}
    superficie={1:'Hard',2:'Clay',3:'I.hard',4:'Carpet',5:'Grass'}.get(torneo.get('courtId'))
    superficie=(torneo.get('court') or {}).get('name') or superficie
    rival=b if gano else a
    return {'id':raw.get('id'),'ts':fecha.timestamp(),'gano':gano,'juegos_favor':gf if gano else gc,
            'juegos_contra':gc if gano else gf,'superficie':superficie or '', 'rival':rival['name'],
            'ranking_rival':None, # No usar el ranking actual de la rival como ranking histórico.
            'nivel':torneo.get('rankId'),'fecha_precision':'exact','torneo':raw.get('tournamentId') or torneo.get('id'),
            'round':raw.get('roundId'),'marcador_original':raw.get('result'),'estado_resultado':'normal','fuente':FUENTE}


def perfil(jugadora):
    base=perfil_basico(jugadora)
    if not base:
        return None
    pid=base['id']
    year=datetime.now(timezone.utc).year
    params={'filter':f'PlayerGroup:singles;GameYear:{year},{year-1}','include':'tournament,tournament.court', 'pageSize':500}
    rows=[];completo=False
    for page in (1,2):
        data=_get('/tennis/v2/wta/player/past-matches/'+pid,dict(params,pageNo=page),86400,context=True)
        if not data:
            break
        raw=data['data']
        # Filtro de año no respetado: no presentar cobertura completa de la consulta.
        fechas=[U._parsear_iso(str(p.get('date') or '')) for p in raw]
        if any(not f or f.year not in (year,year-1) for f in fechas):
            break
        rows.extend(p for r in raw if (p:=normalizar_historial(r,pid)))
        if data.get('hasNextPage') is False:
            completo=True
            break
    dedup={p['id']:p for p in rows if p.get('id')}
    partidos=sorted(dedup.values(),key=lambda p:p['ts'],reverse=True)
    _metrics['histories_verified']+=int(bool(partidos))
    return {'id':pid,'fuente':'Tennis API historial WTA/ITF','partidos':partidos,
            'recientes':[p for p in partidos if p['ts']>=time.time()-120*86400][:10],
            'cobertura_completa_2anios':False, # No atribuir completitud de carrera/WTA a una consulta de tercero.
            'muestras_2anios':len(partidos),'experiencia_carrera_wta':None,'mejor_ranking':base['mejor_ranking'],
            'cobertura_consulta_tennis_api':completo,'servicio':None,'actualizado_utc':base['actualizado_utc']}


def complementar(oficial,alternativo):
    if not alternativo:
        return oficial
    if not oficial:
        return alternativo
    # Mantener las entradas oficiales usadas para puntuar. El complemento es trazable y descriptivo.
    return dict(oficial,complemento_tennis_api=alternativo)


def estado_contexto():
    return dict(_metrics,context_calls_cycle=_context_calls,context_calls_24h=_context_budget.usadas,
                context_limit_24h=28,reserve_for_calendar_results=8)
