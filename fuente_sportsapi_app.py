"""SportsAPI.app v2: una sola cuota gratuita compartida, sólo eventos femeninos.

No confundir con SportAPI.ai (fútbol). No interpreta semillas como ranking,
H2H agregado como partidos fechados ni puntos de rally como sets.
"""
import os
import re
import time
from datetime import datetime, timezone, timedelta
import requests
import utilidades as U
import planificador_datos as P

FUENTE='sportsapi_app'
BASE='https://api.sportsapi.app'
API_KEY=os.environ.get('SPORTSAPI_APP_API_KEY','').strip()
ACTIVO=os.environ.get('SPORTSAPI_APP_ACTIVO','1')!='0'
DEPORTES={'Soccer':'football','Basketball':'basketball','Tennis':'tennis',
          'Ice Hockey':'ice-hockey','Handball':'handball','Volleyball':'volleyball','Rugby':'rugby'}
DEPORTES_ACTIVOS=[s for s in os.environ.get('SPORTSAPI_APP_DEPORTES',','.join(DEPORTES)).split(',') if s in DEPORTES]
presupuesto=U.PresupuestoDiario(FUENTE,100,reserva=0)
_cache=U.CachePersistente('sportsapi_app_v2',12*3600,max_items=512)
_ritmo=U.RitmoPedidos(10,minimo_segundos=6.1)
_pausa=0
_disabled=False
_state=U.cargar_json('sportsapi_app_state_v1.json',{})
if not isinstance(_state,dict):_state={}
_metrics={'auth':'not_checked','calendar_verified':0,'histories_verified':0,'tables_verified':0}


def disponible():return bool(API_KEY) and ACTIVO and not _disabled


def _day():return datetime.now(timezone.utc).date().isoformat()


def _save():U.guardar_json('sportsapi_app_state_v1.json',_state)


def _get(path,params=None,ttl=12*3600,calendar=False):
    global _pausa,_disabled
    if not disponible():return None
    params=params or {}
    hit,data=_cache.get((path,params))
    if hit:return data
    if _state.get('day')!=_day():
        _state.update(day=_day(),calendar_calls=0)
    if (time.time()<_pausa or not P.actual.permitido(FUENTE) or not presupuesto.puede_gastar()
            or calendar and _state.get('calendar_calls',0)>=40):return None
    _ritmo.esperar()
    presupuesto.registrar() # también cuenta fallos de red, de forma conservadora
    if calendar:_state['calendar_calls']=_state.get('calendar_calls',0)+1
    _save()
    try:
        response=requests.get(BASE+path,params=params,headers={'Authorization':'Bearer '+API_KEY},timeout=15)
        U._registrar(FUENTE,response.status_code)
        if response.status_code in (401,403):
            _metrics['auth']='rejected';_disabled=True
            return None
        if response.status_code==429:
            # Retry-After distingue cuota diaria de ritmo por minuto; no confundir
            # RateLimit-Remaining (minuto) con el saldo diario.
            wait=max(1,int(response.headers.get('Retry-After','60')))
            _pausa=time.time()+wait
            P.actual.paused[FUENTE]=_pausa
            return None
        if response.status_code!=200 or len(response.content)>8_000_000:
            _cache.set((path,params),None,ttl=3600);return None
        data=response.json()
        if not isinstance(data,dict) or 'data' not in data:return None
        _metrics['auth']='verified'
        _cache.set((path,params),data,ttl=ttl)
        return data
    except (requests.RequestException,ValueError,TypeError):
        _cache.set((path,params),None,ttl=3600)
        U.log('[sportsapi_app] respuesta no disponible; sin reintento inmediato')
        return None


def _id(value):return type(value) is int and value>0


def normalizar(raw,sport,ahora=None):
    now=time.time() if ahora is None else ahora
    if not isinstance(raw,dict) or raw.get('sport')!=DEPORTES.get(sport):return None
    league,season=raw.get('league') or {},raw.get('season') or {}
    a,b=raw.get('home') or {},raw.get('away') or {}
    if not all(isinstance(v,dict) for v in (league,season,a,b,raw.get('status'),raw.get('homeScore'),raw.get('awayScore'))):return None
    if not all(_id(x) for x in (raw.get('id'),league.get('id'),season.get('id'),a.get('id'),b.get('id'))) or a['id']==b['id']:return None
    na,nb=a.get('name',''),b.get('name','')
    title=league.get('name') or ''
    category=league.get('category') or ''
    if not all(isinstance(v,str) for v in (na,nb,title,category)) or not isinstance(raw.get('round') or {},dict):return None
    scope=title+' '+category
    if not U.participante_definido(na) or not U.participante_definido(nb) or U.firma_equipo(na)==U.firma_equipo(nb):return None
    # Evidencia positiva de género en la competición, no por el nombre supuesto de una jugadora.
    if not U.es_femenino(scope) or re.search(r'\b(?:men|mens|male|srl|simulated|virtual)\b',U.normalizar(scope)):return None
    if sport=='Tennis' and (re.search(r'\b(?:doubles|dobles)\b',U.normalizar(scope)) or '/' in na+nb):return None
    stamp=raw.get('startTime')
    if not isinstance(stamp,str) or not re.search(r'T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$',stamp):return None
    dt=U._parsear_iso(stamp)
    if not dt:return None
    ts=dt.timestamp()
    common={'id':'sapp_'+str(raw['id']),'sportsapi_app_id':raw['id'],'fuente':FUENTE,'deporte':sport,
            'torneo':scope.strip(),'femenino_seguro':True,'historial_aislado':True,
            'contexto_competicion':f"sapp:{sport}:{league['id']}:{season['id']}",
            'league_id':league['id'],'season_ref':season['id'],'season_label':season.get('year'),
            'round_name':(raw.get('round') or {}).get('name'),
            'local':{'id':'sapp:'+str(a['id']),'sportsapi_app_id':a['id'],'nombre':na},
            'visita':{'id':'sapp:'+str(b['id']),'sportsapi_app_id':b['id'],'nombre':nb}}
    status=raw.get('status') or {}
    if status.get('type')=='notstarted' and status.get('phase')=='notstarted' and now<ts<=now+86400:
        # Ningún marcador ya iniciado puede convertirse en fixture pre-partido.
        if raw.get('winner') is not None or any((raw.get(s) or {}).get('current') not in (None,0) for s in ('homeScore','awayScore')):return None
        return dict(common,tipo_estado='pre',startTimestamp=int(ts),horario=U.formatear_hora_arg(ts))
    if status.get('type')!='finished' or status.get('phase')!='finished' or status.get('finish')!='regular' or not now-90*86400<=ts<now:return None
    scores=[]
    for side in ('homeScore','awayScore'):
        row=raw.get(side) or {}
        value=row.get('normalTime') if sport in ('Soccer','Ice Hockey','Handball','Rugby') else row.get('current')
        if value is None:value=row.get('current') # finish regular acredita ausencia de prórroga
        if type(value) is not int or value<0:return None
        scores.append(value)
    if sport=='Volleyball' and not(max(scores)==3 and min(scores)<=2):return None
    if sport=='Tennis' and not(max(scores)==2 and min(scores)<=1):return None
    expected='home' if scores[0]>scores[1] else 'away' if scores[1]>scores[0] else 'draw'
    if raw.get('winner')!=expected:return None
    return dict(common,fecha=dt.isoformat(),id_local=common['local']['id'],id_visita=common['visita']['id'],
                nom_local=na,nom_visita=nb,puntos_local=scores[0],puntos_visita=scores[1],
                estado_resultado='normal',_outcome_status='normal',_calendario_completo=False,_period_scope='regulation')


def _catalogo():
    data=_get('/v2/sports',ttl=86400,calendar=True)
    rows=(data or {}).get('data')
    return {p.get('slug') for p in rows if isinstance(p,dict)} if isinstance(rows,list) else set()


def deportes_ciclo(sports):
    # Cambia el orden de descubrimiento sin privilegiar una disciplina fija.
    shift=int(time.time()//(6*3600))%len(sports)
    return sports[shift:]+sports[:shift]


def obtener_eventos(sport):
    if sport not in DEPORTES_ACTIVOS or not disponible() or DEPORTES[sport] not in _catalogo():return []
    output={}
    days=[(datetime.now(timezone.utc)+timedelta(days=n)).date().isoformat() for n in (0,1)]
    cursors=_state.setdefault('cursors',{})
    pages=_state.setdefault('pages',{})
    for key in list(pages):
        if key[-10:] not in days:pages.pop(key,None);cursors.pop(key,None)
    for day in days:
        key=sport+'|'+day
        page=cursors.get(key,0)
        params={'sport':DEPORTES[sport],'date':day,'page':page}
        data=_get('/v2/fixtures',params,calendar=True)
        meta=(data or {}).get('meta') or {}
        if data and (meta.get('sport'),meta.get('date'),meta.get('page'))==(DEPORTES[sport],day,page):
            pages[key]=sorted(set(pages.get(key,[])+[page]))
            cursors[key]=page+1 if meta.get('hasNextPage') is True and page<99 else 0
            if meta.get('hasNextPage') or meta.get('complete') is not True:
                import cobertura_radar
                cobertura_radar.actual.truncado(FUENTE,sport)
        for seen in pages.get(key,[]):
            hit,cached=_cache.get(('/v2/fixtures',dict(params,page=seen)))
            if not hit or not isinstance((cached or {}).get('data'),list):continue
            for raw in cached['data']:
                event=normalizar(raw,sport)
                if event and event.get('tipo_estado')=='pre':output[event['id']]=event
    _save()
    _metrics['calendar_verified']+=len(output)
    return list(output.values())


def historial_equipo(evento,lado):
    sport=evento.get('deporte')
    pid=(evento.get(lado) or {}).get('sportsapi_app_id')
    if not _id(pid) or sport=='Tennis':return []
    data=_get(f'/v2/teams/{pid}/fixtures',{'type':'recent','page':0})
    if (data or {}).get('meta',{}).get('type')!='recent' or not isinstance((data or {}).get('data'),list):return []
    output=[]
    for raw in (data or {}).get('data',[]):
        row=normalizar(raw,sport)
        if (row and 'fecha' in row and row['contexto_competicion']==evento.get('contexto_competicion')
                and 'sapp:'+str(pid) in (row['id_local'],row['id_visita'])):output.append(row)
    _metrics['histories_verified']+=int(bool(output))
    return sorted({p['id']:p for p in output}.values(),key=lambda p:p['fecha'],reverse=True)[:10]


def tabla_partido(evento):
    league,season=evento.get('league_id'),evento.get('season_ref')
    if not _id(league) or not _id(season) or evento.get('fuente')!=FUENTE or evento.get('deporte')=='Tennis':return None,0
    if re.search(r'playoff|quarter|semi|final|knockout|round of|qualif',U.normalizar(evento.get('round_name') or '')):return None,0
    data=_get(f'/v2/leagues/{league}/standings',{'season':season,'group':'all','type':'total'})
    meta=(data or {}).get('meta') or {}
    if meta.get('season')!=season or meta.get('type')!='total' or not isinstance((data or {}).get('data'),list):return None,0
    ids={evento[s]['id'] for s in ('local','visita')}
    candidates=[]
    for group in (data or {}).get('data',[]):
        if not isinstance(group,dict) or not isinstance(group.get('rows'),list):continue
        output={}
        for row in group['rows']:
            if not isinstance(row,dict):break
            team=row.get('team') or {}
            if not isinstance(team,dict):break
            vals=[row.get(k) for k in ('position','played','wins','draws','losses')]
            if not _id(team.get('id')) or any(type(v) is not int or v<0 for v in vals):break
            pos,played,w,d,l=vals
            if pos<1 or played!=w+d+l or 'sapp:'+str(team['id']) in output:break
            output['sapp:'+str(team['id'])]={'posicion':pos,'victorias':w,'empates':d,'derrotas':l,
                'nombre':team.get('name'),'fuente':FUENTE,'season':season,
                'dif_neta':row.get('scoreDifference') if type(row.get('scoreDifference')) is int else 0}
        else:
            if ids<=set(output) and len(output)>=2:
                if all(U.firma_equipo(output[evento[s]['id']]['nombre'] or '')==U.firma_equipo(evento[s]['nombre']) for s in ('local','visita')):
                    candidates.append((bool(group.get('overall')),output))
    overall=[t for is_overall,t in candidates if is_overall]
    chosen=overall if len(overall)==1 else [t for _,t in candidates]
    if len(chosen)!=1:return None,0
    _metrics['tables_verified']+=1
    return chosen[0],len(chosen[0])


def resultados_evaluacion(evento):
    from resultados_evaluacion import de_historial
    if evento.get('fuente')!=FUENTE or not _id(evento.get('sportsapi_app_id')):return []
    raw=_get('/v2/fixtures/'+str(evento.get('sportsapi_app_id')),ttl=3600)
    row=normalizar((raw or {}).get('data'),evento.get('deporte'))
    result=de_historial(row,evento['deporte'],FUENTE) if row and 'fecha' in row else None
    if result and evento.get('deporte')=='Tennis':
        sets=_sets_tenis((raw or {}).get('data') or {})
        if not sets:return []
        result.update(score_unit='sets',sets=sets)
    return [result] if result else []


def _sets_tenis(raw):
    home=(raw.get('homeScore') or {}).get('periods') or {}
    away=(raw.get('awayScore') or {}).get('periods') or {}
    keys=['period'+str(i) for i in (1,2,3) if 'period'+str(i) in home]
    if len(keys) not in (2,3) or set(home)!=set(away) or set(keys)!=set(home):return None
    pairs=[[home[k],away[k]] for k in keys]
    def valid(a,b):
        return all(type(v) is int and v>=0 for v in (a,b)) and (max(a,b)==6 and min(a,b)<=4 or max(a,b)==7 and min(a,b) in (5,6))
    if not all(valid(*p) for p in pairs):return None
    totals=[sum(a>b for a,b in pairs),sum(b>a for a,b in pairs)]
    if totals!=[(raw.get('homeScore') or {}).get('current'),(raw.get('awayScore') or {}).get('current')]:return None
    return pairs


def perfil_tenis(evento,lado):
    pid=(evento.get(lado) or {}).get('sportsapi_app_id')
    if evento.get('deporte')!='Tennis' or not _id(pid):return None
    data=_get(f'/v2/teams/{pid}/fixtures',{'type':'recent','page':0})
    if not isinstance((data or {}).get('data'),list) or (data or {}).get('meta',{}).get('type')!='recent':return None
    output={}
    for raw in data['data']:
        row=normalizar(raw,'Tennis')
        sets=_sets_tenis(raw) if row and 'fecha' in row else None
        if not sets or 'sapp:'+str(pid) not in (row['id_local'],row['id_visita']):continue
        local=row['id_local']=='sapp:'+str(pid)
        a,b=sum(x for x,y in sets),sum(y for x,y in sets)
        output[row['id']]={'ts':U._parsear_iso(row['fecha']).timestamp(),'gano':(row['puntos_local']>row['puntos_visita'])==local,
            'rival':row['nom_visita'] if local else row['nom_local'],'ranking_rival':None,
            'torneo':row['league_id'],'round':str((raw.get('round') or {}).get('number')),
            'superficie':'','fecha_precision':'exact','estado_resultado':'normal',
            'juegos_favor':a if local else b,'juegos_contra':b if local else a,'fuente':'SportsAPI.app historial'}
    if not output:return None
    rows=sorted(output.values(),key=lambda p:p['ts'],reverse=True)
    _metrics['histories_verified']+=1
    return {'fuente':'SportsAPI.app historial','partidos':rows,'recientes':rows[:10],
            'muestras_2anios':len(rows),'ventana_historial_dias':90,'cobertura_completa_2anios':False,
            'experiencia_carrera_wta':None,'mejor_ranking':None,'servicio':None}


def estado_contexto():
    return dict(_metrics,calendar_requests_day=_state.get('calendar_calls',0) if _state.get('day')==_day() else 0,
                calendar_limit_day=40,quota_shared_across_sports=True,
                integrated_sports=DEPORTES_ACTIVOS,authenticated_data_verified=_metrics['auth']=='verified')
