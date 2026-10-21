"""Adaptadores oficiales de vóley nacional: HTML público, IDs/edición/fechas verificables."""
import re
import time
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs
import utilidades as U
from fuentes_publicas import Cliente


class TablasHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[];self.stack=[];self.rows=[];self.cells=[];self.links=[];self.blocked=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style'):self.blocked+=1
        if tag=='table':self.stack.append({'attrs':attrs,'rows':[]})
        if tag=='tr' and self.stack:self.rows.append((self.stack[-1],[]))
        if tag in ('td','th') and self.rows:self.cells.append({'row':self.rows[-1][1],'text':[],'attrs':attrs,'links':[]})
        if tag=='a' and attrs.get('href'):
            self.links.append((attrs['href'],attrs))
            for cell in self.cells:cell['links'].append(attrs['href'])
    def handle_data(self,data):
        if not self.blocked:
            for cell in self.cells:cell['text'].append(data)
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.blocked=max(0,self.blocked-1)
        if tag in ('td','th') and self.cells:
            cell=self.cells.pop();cell['text']=' '.join(' '.join(cell['text']).split());cell['row'].append(cell)
        if tag=='tr' and self.rows:
            table,row=self.rows.pop()
            if row:table['rows'].append(row)
        if tag=='table' and self.stack:self.tables.append(self.stack.pop())


def parse_html(text):
    if not text or len(text)>8_000_000:return None
    parser=TablasHTML();parser.feed(text);return parser


def numero(text):
    if not re.fullmatch(r'\d+',str(text).strip()):return None
    return int(str(text).strip())


def temporada_actual(now=None):
    date=datetime.fromtimestamp(time.time() if now is None else now,timezone.utc)
    start=date.year if date.month>=8 else date.year-1
    return f'{start}/{start+1}'


class Oficial:
    def __init__(self,fuente):
        self.fuente=fuente
        self.cache=U.CachePersistente(fuente+'_voley_v1',6*3600,max_items=32)
        self.cliente=Cliente(fuente,self.cache,limite=24)
        self.historial=[];self.eventos=[];self.tabla={};self.edicion=None
        self.details_cycle=0
        self.status={'state':'not_loaded','teams':0,'history':0,'events':0}
        self.last_verified=0
        self._saved_at=0
        if fuente in ('lvf','lnv'):
            snapshot=U.cargar_json(fuente+'_contexto_validado_v1.json',{})
            if isinstance(snapshot,dict):
                self.last_verified=snapshot.get('verified_at',0)
                self.edicion=snapshot.get('edition')
                if self.last_verified and self._vigente():
                    self.tabla=snapshot.get('table') or {}
                    self.historial=snapshot.get('history') or []
                    for name in ('_lvf_pending','_lnv_pid','_lnv_expected'):
                        if name in snapshot:setattr(self,name,snapshot[name])
                    self.status.update(state='last_valid_context',teams=len(self.tabla),history=len(self.historial),
                                       edition=self.edicion,last_verified_utc=self.last_verified)
                elif snapshot:self.invalidar('expired_context')

    def _vigente(self, now=None):
        now=time.time() if now is None else now
        if not isinstance(self.last_verified,(int,float)):return False
        if not self.last_verified:return True # contextos construidos por parsers/pruebas
        if not 0<=now-self.last_verified<=48*3600:return False
        if self.fuente=='lvf':return self.edicion=='lvf:a1:'+temporada_actual(now)
        if self.fuente=='lnv':
            return temporada_actual(self.last_verified)==temporada_actual(now)
        return True

    def invalidar(self, reason):
        self.tabla={};self.historial=[];self.eventos=[];self.edicion=None;self.last_verified=0
        for name in ('_lvf_pending','_lnv_pid','_lnv_expected'):
            self.__dict__.pop(name,None)
        self.status.update(state=reason,teams=0,history=0,events=0,edition=None)
        if self.fuente in ('lvf','lnv'):
            U.guardar_json(self.fuente+'_contexto_validado_v1.json',{})

    def no_disponible(self, reason='unavailable'):
        if self.tabla and self.last_verified and self._vigente():
            self.status.update(state='last_valid_context',refresh_error=reason,
                               last_verified_utc=self.last_verified,max_age_hours=48)
        else:self.invalidar('expired_context' if self.last_verified else reason)

    def guardar_contexto(self, verified=False):
        if self.fuente not in ('lvf','lnv'):return
        now=time.time()
        if verified:self.last_verified=now
        if not self.tabla or not self.last_verified:return
        snapshot={'edition':self.edicion,'verified_at':self.last_verified,'table':self.tabla,'history':self.historial}
        for name in ('_lvf_pending','_lnv_pid','_lnv_expected'):
            if hasattr(self,name):snapshot[name]=getattr(self,name)
        signature=U.CachePersistente._clave({k:v for k,v in snapshot.items() if k!='verified_at'})
        if signature!=getattr(self,'_saved_signature',None) or now-self._saved_at>=3600:
            if U.guardar_json(self.fuente+'_contexto_validado_v1.json',snapshot):
                self._saved_signature=signature;self._saved_at=now
        self.status.update(last_verified_utc=self.last_verified,max_age_hours=48)
        if verified:self.status.pop('refresh_error',None)


    def cargar_lvf(self,text,now=None):
        now=time.time() if now is None else now
        parser=parse_html(text)
        if not parser:return False
        seasons=re.findall(r'class=["\']dropdown-item active["\'][^>]*href=["\'][^"\']*stagione=(\d{4})[^"\']*["\'][^>]*>\s*<b>(\d{4}/\d{4})</b>',text)
        seasons={(a,b) for a,b in seasons if b==temporada_actual(now) and b.startswith(a+'/')}
        if len(seasons)!=1:return False
        season=next(iter(seasons))[1]
        # Sólo la página oficial A1 seleccionada, no una tabla A2 de otro grupo.
        if not re.search(r'dropdown-item active[^>]*[^<]*<b>LVF A1',text,re.I):return False
        tabla={};matrix=None
        for table in parser.tables:
            rows=table['rows']
            if not rows:continue
            heads=[cell['text'] for cell in rows[0]]
            if heads[:6]==['Pos','Squadra','PT','G','V','P']:
                for row in rows[1:]:
                    values=[c['text'] for c in row]
                    if len(values)<16:continue
                    pos,played,w,l,sw,sl=map(numero,[values[i] for i in (0,3,4,5,12,13)])
                    if None in (pos,played,w,l,sw,sl) or played!=w+l or not pos:return False
                    links=[u for u in row[1]['links'] if re.search(r'/club/|/squadra/|/team/',u)]
                    key=U.firma_equipo(values[1])
                    if not key or key in tabla:return False
                    tabla[key]={'posicion':pos,'victorias':w,'derrotas':l,'empates':0,'dif_neta':sw-sl,
                                'nombre':values[1],'team_ref':links[0] if len(set(links))==1 else key,
                                'fuente':self.fuente,'points_for':numero(values[14]),'points_against':numero(values[15]),'season':season}
            elif len(heads)>3 and not heads[0] and any(U.firma_equipo(h) in tabla for h in heads[1:]):matrix=rows
        if len(tabla)<6 or not matrix or sorted(r['posicion'] for r in tabla.values())!=list(range(1,len(tabla)+1)):return False
        if self.edicion!='lvf:a1:'+season:self.historial=[]
        self.edicion='lvf:a1:'+season
        hist=[]
        # La matriz verifica rival, orientación y marcador; fecha/hora se carga desde match-center.
        for row in matrix[1:]:
            if len(row)!=len(matrix[0]):continue
            a=U.firma_equipo(row[0]['text'])
            if a not in tabla:continue
            for i,cell in enumerate(row[1:],1):
                b=U.firma_equipo(matrix[0][i]['text'])
                if b not in tabla or a==b:continue
                match=re.fullmatch(r'([0-3])\s*-\s*([0-3])',cell['text'])
                ids={m.group(1) for u in cell['links'] if (m:=re.search(r'/match-center/(\d+)',u))}
                if match and len(ids)==1 and max(map(int,match.groups()))==3 and min(map(int,match.groups()))<3:
                    hist.append({'match_id':next(iter(ids)),'a':a,'b':b,'score':list(map(int,match.groups()))})
        self.tabla=tabla;self._lvf_pending=hist;self.status.update(state='verified_table',teams=len(tabla),edition=self.edicion)
        return True

    def cargar_lnv(self,text,edition,now=None):
        now=time.time() if now is None else now
        parser=parse_html(text)
        if not parser or 'Saforelle VOLSTAR' not in html.unescape(text):return False
        tabla={};hist=[]
        for table in parser.tables:
            rows=table['rows']
            if not rows:continue
            heads=[c['text'] for c in rows[0]]
            if heads[:3]==['Equipe','Points','Matchs']:
                # Cabecera multicolumna; valores completos en las filas exteriores, no la tabla de logotipos.
                for row in rows[2:]:
                    values=[c['text'] for c in row]
                    if len(values)<9:continue
                    nums=[numero(x) for x in values[1:9]]
                    if None in nums:continue
                    points,played,w,l,sw,sl,pf,pa=nums
                    names=[n for n in re.split(r'\s{2,}',values[0]) if n]
                    name=values[0].strip()
                    if played!=w+l or not name:return False
                    key=U.firma_equipo(name)
                    if key in tabla:return False
                    tabla[key]={'posicion':len(tabla)+1,'victorias':w,'derrotas':l,'empates':0,'dif_neta':sw-sl,
                                'nombre':name,'fuente':self.fuente,'points_for':pf,'points_against':pa,'season':'unknown','edition':edition}
            if table['attrs'].get('id')=='tableRisultati':
                for row in rows:
                    for cell in row:
                        title=cell['attrs'].get('title','')
                        p=_resultado_frances(title,now)
                        if p:hist.append(p)
        if len(tabla)<6 or not hist:return False
        if not any(0<=now-p['ts']<=30*86400 for p in hist):return False
        # Edición descubierta en la web femenina actual; no inventar temporada numérica.
        self.edicion='lnv:d1f:'+str(edition)
        # Alias oficiales del mismo sitio para nombres cortos de resultados vs tabla.
        aliases={'beziers':'BEZIERS VOLLEY','mulhouse':'VOLLEY MULHOUSE ALSACE','levallois paris':'LEVALLOIS',
                 'cannes':'RACING CLUB DE CANNES','le cannet':'VIRTUS LE CANNET','evreux':'EVREUX VOLLEY-BALL',
                 'nantes':'NEPTUNES NANTES','chamalieres':'VBC CHAMALIERES','france avenir':'INSTITUT FEDERAL DE VOLLEY BALL',
                 'terville florange':'TERVILLE-FLORANGE OLYMPIQUE-CLUB','st die':'SAINT-DIE',
                 'vandoeuvre nancy':'VANDOEUVRE NANCY','bordeaux merignac':'BORDEAUX MERIGNAC'}
        self.tabla=tabla
        output=[]
        for p in hist:
            a=U.firma_equipo(aliases.get(U.normalizar(p['a']),p['a']))
            b=U.firma_equipo(aliases.get(U.normalizar(p['b']),p['b']))
            if a not in tabla or b not in tabla or a==b:continue
            output.append(self._historico(a,b,p['score'],p['ts'],U.firma_partido(a,b)+'_'+str(p['ts'])))
        self.tabla=tabla;self.historial=output;self._lnv_expected=list(output)
        self.status.update(state='verified_table_and_results',teams=len(tabla),history=len(output),edition=self.edicion)
        return True

    def _historico(self,a,b,score,ts,mid,set_points=None):
        return {'id':self.fuente+'_'+str(mid),'fuente':self.fuente,'deporte':'Volleyball','fecha':U.ts_a_iso_utc(ts),
                'startTimestamp':int(ts),'contexto_competicion':self.edicion,'historial_aislado':True,'femenino_seguro':True,
                'nom_local':self.tabla[a]['nombre'] if a in self.tabla else a,'nom_visita':self.tabla[b]['nombre'] if b in self.tabla else b,
                'id_local':self.fuente+':'+a,'id_visita':self.fuente+':'+b,'puntos_local':score[0],'puntos_visita':score[1],
                'puntos_por_set':set_points or [],'_outcome_status':'normal'}

    def tabla_para_evento(self,evento):
        if evento.get('deporte')!='Volleyball' or not self._vigente():return None,0
        if evento.get('fuente')==self.fuente and evento.get('contexto_competicion')!=self.edicion:return None,0
        # Para respaldar un tercero exigir competición nacional explícita.
        if any(U.categoria_equipo(str(value))!=((),False) for value in [evento.get('torneo','')]+[(evento.get(l) or {}).get('nombre','') for l in ('local','visita')]):return None,0
        torneo=U.normalizar(evento.get('torneo',''))
        if evento.get('fuente')!=self.fuente:
            scope=bool(re.search(r'ital|serie a1|a1 fineco',torneo)) if self.fuente=='lvf' else bool(re.search(r'franc|saforelle|ligue a',torneo))
            if not scope or re.search(r'champions|cev|world|cup|coupe|coppa',torneo):return None,0
        output={}
        for lado in ('local','visita'):
            player=evento.get(lado) or {};key=U.firma_equipo(player.get('nombre',''))
            resolved=self.resolver(player.get('nombre',''))
            matches=[row for name,row in self.tabla.items() if name==resolved]
            if len(matches)!=1:return None,0
            output[player['id']]=matches[0]
        return output,len(self.tabla)

    def resolver(self,nombre):
        key=U.firma_equipo(nombre)
        if key in self.tabla:return key
        # Alias explícitos de los clubes de las tablas oficiales actuales; no similitud difusa.
        aliases={'lvf':{'conegliano':'Imoco Conegliano','milano':'Vero Volley Milano','novara':'Gorgonzola Novara',
                        'chieri':'Fenera Chieri','scandicci':'Del Bene Scandicci','bergamo':'Volley Bergamo',
                        'vallefoglia':'Savio Vallefoglia','firenze':'Bisonte Firenze','brescia':'Millenium Brescia',
                        'cuneo':'Volley Cuneo','macerata':'Macerata','talmassons':'Talmassons','uyba':'Uyba'},
                 'lnv':{'beziers':'Beziers Volley','mulhouse':'Volley Mulhouse Alsace','levallois paris':'Levallois',
                        'cannes':'Racing Club Cannes','le cannet':'Virtus Le Cannet','evreux':'Evreux Volley Ball',
                        'nantes':'Neptunes Nantes','chamalieres':'VBC Chamalieres','france avenir':'Institut Federal Volley Ball',
                        'terville florange':'Terville Florange Olympique Club','st die':'Saint Die'}}
        target=aliases.get(self.fuente,{}).get(U.normalizar(nombre).replace(' women','').strip())
        if not target:return None
        tokens=set(U.firma_equipo(target).split('-'))
        matches=[name for name in self.tabla if tokens<=set(name.split('-'))]
        return matches[0] if len(matches)==1 else None

    def historial_para_evento(self,evento,lado):
        table,_=self.tabla_para_evento(evento)
        if not table:return []
        ids={}
        for l in ('local','visita'):
            team=evento[l];key=self.resolver(team['nombre'])
            if not key:return []
            ids[self.fuente+':'+key]=team['id']
        tid=evento[lado]['id']
        rows=[dict(p,id_local=ids.get(p['id_local'],p['id_local']),id_visita=ids.get(p['id_visita'],p['id_visita'])) for p in self.historial]
        return sorted((p for p in rows if tid in (p['id_local'],p['id_visita'])),key=lambda p:p['fecha'],reverse=True)[:10]

    def resultados_para_evento(self,evento):
        if not self.tabla_para_evento(evento)[0]:return []
        a,b=[self.fuente+':'+str(self.resolver(evento[l]['nombre'])) for l in ('local','visita')]
        rows=[p for p in self.historial if {p['id_local'],p['id_visita']}=={a,b} and p['startTimestamp']==evento.get('startTimestamp')]
        if len(rows)!=1:return []
        from resultados_evaluacion import de_historial
        p=rows[0]
        reverse=p['id_local']!=a
        score=[p['puntos_visita'],p['puntos_local']] if reverse else [p['puntos_local'],p['puntos_visita']]
        row=dict(p,nom_local=evento['local']['nombre'],nom_visita=evento['visita']['nombre'],puntos_local=score[0],puntos_visita=score[1])
        result=de_historial(row,'Volleyball',self.fuente)
        if not result:return []
        result['original_participant_names']=[p['nom_local'],p['nom_visita']]
        result['original_score']=[p['puntos_local'],p['puntos_visita']]
        if reverse and result.get('set_points'):result['set_points']=[[b,a] for a,b in result['set_points']]
        result['verified_event_ref']={'source':evento.get('fuente'),'id':evento.get('id')}
        result['link_method']='official_competition_alias_pair_exact_time'
        return [result]

    def historial_equipo(self,evento,lado):
        if evento.get('contexto_competicion')!=self.edicion:return []
        tid=(evento.get(lado) or {}).get('id')
        return sorted((p for p in self.historial if tid in (p['id_local'],p['id_visita'])),key=lambda p:p['fecha'],reverse=True)[:10]


def _resultado_frances(title,now):
    match=re.fullmatch(r'\s*(.+?)\s+([0-3])\s*-\s*([0-3])\s+(.+?)\s*//\s*\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{2}):(\d{2})\s*',title)
    if not match:return None
    a,sa,sb,b,day,month,year,hour,minute=match.groups()
    months={'janvier':1,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'aout':8,'septembre':9,'octobre':10,'novembre':11,'decembre':12}
    mon=months.get(U.normalizar(month))
    if not mon or max(int(sa),int(sb))!=3 or min(int(sa),int(sb))>=3:return None
    try:ts=datetime(int(year),mon,int(day),int(hour),int(minute),tzinfo=ZoneInfo('Europe/Paris')).timestamp()
    except ValueError:return None
    if not 0<=now-ts<=90*86400:return None
    return {'a':a,'b':b,'score':[int(sa),int(sb)],'ts':ts}


def _puntos_validos(sets,score):
    if len(sets)!=sum(score) or len(sets) not in (3,4,5):return False
    wins=[0,0]
    for i,(a,b) in enumerate(sets):
        target=15 if i==4 else 25
        if max(a,b)<target or a==b or (max(a,b)>target and abs(a-b)!=2) or (max(a,b)==target and min(a,b)>target-2):return False
        wins[0 if a>b else 1]+=1
    return wins==score and any(min(a,b)>0 for a,b in sets)


def detalle_lvf(text,pending,season,now=None):
    now=time.time() if now is None else now
    block=re.search(r'tabellone-alto-match-center(.*?)riga-arbitri',text,re.S)
    if not block:return None
    block=block.group(1)
    names=re.findall(r'<b class="nome-squadra">(.*?)</b>',block,re.S)
    if len(names)!=2 or [U.firma_equipo(html.unescape(n).strip()) for n in names]!=[pending['a'],pending['b']]:return None
    stamp=re.search(r'>(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})<',block)
    score=re.search(r'<span>([0-3])</span>\s*<span>([0-3])</span>',block)
    if not stamp or not score or list(map(int,score.groups()))!=pending['score']:return None
    if re.search(r'forfait|tavolino|ritir|annullat|sospes',html.unescape(re.sub('<[^>]+>',' ',block)),re.I):return None
    try:ts=datetime.strptime(' '.join(stamp.groups()),'%d/%m/%Y %H:%M').replace(tzinfo=ZoneInfo('Europe/Rome')).timestamp()
    except ValueError:return None
    year=int(season[:4]);date=datetime.fromtimestamp(ts,ZoneInfo('Europe/Rome'))
    if not datetime(year,8,1,tzinfo=ZoneInfo('Europe/Rome'))<=date<datetime(year+1,8,1,tzinfo=ZoneInfo('Europe/Rome')) or not 0<=now-ts<=90*86400:return None
    # Capturar sólo parciales después del marcador, evitando números de fecha/IDs.
    scoreblock=block[score.end():].split('</div>',1)[0]
    sets=[list(map(int,p)) for p in re.findall(r'\b(\d{1,2})-(\d{1,2})\b',scoreblock)]
    if not _puntos_validos(sets,pending['score']):return None
    return ts,sets


def cargar_lvf(oficial):
    text=oficial.cliente.pedir('https://www.legavolleyfemminile.it/classifica/',{'no_cache_sa':1},xml=True)
    if not text:
        oficial.no_disponible();return
    if not oficial.cargar_lvf(text):
        oficial.invalidar('rejected_schema_or_season');return
    oficial.guardar_contexto(verified=True)
    season=oficial.edicion.split(':')[-1]
    completar_lvf(oficial, equipos=set())


def completar_lvf(oficial, equipos):
    if not oficial.edicion or not hasattr(oficial, '_lvf_pending'):
        return
    season=oficial.edicion.split(':')[-1]
    expected={oficial.fuente+'_'+p['match_id']:p for p in oficial._lvf_pending}
    rows=[p for p in oficial.historial if p['id'] in expected and
          [p['puntos_local'],p['puntos_visita']]==expected[p['id']]['score'] and
          0<=time.time()-p['startTimestamp']<=90*86400]
    nuevos=0
    for p in oficial._lvf_pending:
        url='https://www.legavolleyfemminile.it/match-center/'+p['match_id']+'/'
        params={'no_cache_sa':1}
        hit,_=oficial.cache.get((url,params))
        if not hit and (oficial.details_cycle>=4 or not ({p['a'],p['b']} & equipos)):continue
        nuevos+=int(not hit)
        oficial.details_cycle+=int(not hit)
        text=oficial.cliente.pedir(url,params,ttl=86400,xml=True)
        result=detalle_lvf(text or '',p,season)
        if result:
            ts,sets=result
            rows.append(oficial._historico(p['a'],p['b'],p['score'],ts,p['match_id'],sets))
    oficial.historial=list({p['id']:p for p in rows}.values())
    oficial.guardar_contexto()
    oficial.status.update(history=len(oficial.historial),state='verified_table_and_results' if rows else 'verified_table')


def cargar_lnv(oficial):
    page=oficial.cliente.pedir('https://www.lnv.fr/d1f/statistiques',xml=True)
    if not page:
        oficial.no_disponible();return
    ids=set(re.findall(r'https://lnv-web\.dataproject\.com/Statistics_AllPlayers\.aspx\?ID=(\d+)',page))
    if len(ids)!=1:
        oficial.invalidar('ambiguous_edition');return
    edition=next(iter(ids))
    if oficial.edicion and oficial.edicion!='lnv:d1f:'+edition:
        oficial.invalidar('edition_changed')
    # El PID se descubre en los enlaces públicos de la edición actual, nunca queda fijado de un año viejo.
    home=oficial.cliente.pedir('https://lnv-web.dataproject.com/CompetitionHome.aspx',{'ID':edition},xml=True)
    if not home:
        oficial.no_disponible();return
    links=re.findall(r'CompetitionStandings\.aspx\?ID='+edition+r'(?:&amp;|&)PID=(\d+)',home or '')
    if len(set(links))!=1:
        oficial.invalidar('unknown_stage');return
    text=oficial.cliente.pedir('https://lnv-web.dataproject.com/CompetitionStandings.aspx',{'ID':edition,'PID':links[0]},xml=True)
    if not text:
        oficial.no_disponible();return
    previous=list(oficial.historial)
    if not oficial.cargar_lnv(text,edition):
        oficial.invalidar('rejected_schema_or_dates');return
    # Conservar sólo parciales ya verificados que coinciden con la matriz actual.
    def key(p):return (p['startTimestamp'],p['id_local'],p['id_visita'],p['puntos_local'],p['puntos_visita'])
    expected={key(p) for p in oficial._lnv_expected}
    oficial.historial=[p for p in previous if p.get('puntos_por_set') and key(p) in expected]
    oficial.guardar_contexto(verified=True)
    oficial._lnv_pid=links[0]
    completar_lnv(oficial,edition,links[0],equipos=set())


def detalle_lnv(text,oficial,expected,now=None):
    now=time.time() if now is None else now
    def field(name):
        hit=re.search(r'<span id="Content_Main_'+name+r'"[^>]*>([^<]*)</span>',text)
        return html.unescape(hit.group(1)).strip() if hit else None
    a,b=field('LBL_HomeTeam'),field('LBL_GuestTeam')
    score=[numero(field('LBL_WonSetHome')),numero(field('LBL_WonSetGuest'))]
    when=field('LB_DateTime')
    if not a or not b or None in score or not when:return None
    parsed=_resultado_frances(f'{a} {score[0]} - {score[1]} {b} // '+when.replace(' - ', ' '),now)
    if not parsed or parsed['ts']!=expected['startTimestamp'] or score!=[expected['puntos_local'],expected['puntos_visita']]:return None
    if [oficial.fuente+':'+str(oficial.resolver(n)) for n in (a,b)]!=[expected['id_local'],expected['id_visita']]:return None
    sets=[list(map(int,p)) for p in re.findall(r'(\d{1,2})/(\d{1,2})',field('LB_SetsPartials') or '')]
    if not _puntos_validos(sets,score):return None
    return dict(expected,puntos_por_set=sets)


def completar_lnv(oficial,edition,pid,equipos=None):
    text=oficial.cliente.pedir('https://lnv-web.dataproject.com/CompetitionMatches.aspx',{'ID':edition,'PID':pid},ttl=86400,xml=True)
    if not text:
        return # Un fallo de detalle no borra los resultados ya verificados.
    expected_rows=getattr(oficial,'_lnv_expected',oficial.historial)
    dates={p['startTimestamp'] for p in expected_rows}
    candidates={}
    for hit in re.finditer(r'<span id="[^"]+_LB_DataOra">(\d{2}/\d{2}/\d{4} - \d{2}:\d{2})</span>',text):
        try:ts=int(datetime.strptime(hit.group(1),'%d/%m/%Y - %H:%M').replace(tzinfo=ZoneInfo('Europe/Paris')).timestamp())
        except ValueError:continue
        if ts not in dates:continue
        prefix=html.unescape(text[max(0,hit.start()-4500):hit.start()])
        links=re.findall(r'MatchStatistics\.aspx\?mID=(\d+)&ID='+str(edition)+r'&CID=(\d+)&PID='+str(pid),prefix)
        if links:
            mid,cid=links[-1];candidates[mid]=(ts,cid)
    output=list(oficial.historial);new=0
    for mid,(ts,cid) in candidates.items():
        params={'mID':mid,'ID':edition,'CID':cid,'PID':pid,'type':'LegList'}
        url='https://lnv-web.dataproject.com/MatchStatistics.aspx'
        hit,_=oficial.cache.get((url,params))
        relevant=any(p['startTimestamp']==ts and
                     (equipos is None or any(U.firma_equipo(p.get('nom_'+s,'')) in equipos for s in ('local','visita')))
                     for p in expected_rows)
        if not hit and (oficial.details_cycle>=4 or not relevant):continue
        new+=int(not hit)
        oficial.details_cycle+=int(not hit)
        page=oficial.cliente.pedir(url,params,ttl=86400,xml=True)
        for expected in expected_rows:
            if expected['startTimestamp']!=ts:continue
            result=detalle_lnv(page or '',oficial,expected)
            if result:output.append(dict(result,id=oficial.fuente+'_'+mid))
    oficial.historial=list({(p['startTimestamp'],p['id_local'],p['id_visita']):p for p in output}.values())
    oficial.guardar_contexto()
    oficial.status.update(history=len(oficial.historial),state=(
        'verified_table_and_played_results' if oficial.historial else 'verified_table'))
