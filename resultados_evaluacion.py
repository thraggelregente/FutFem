"""Resultados versionados: nunca convertir ausencia, retiro o conflicto en derrota."""
import time
from datetime import datetime, timezone
import utilidades as U
import auditoria_decisiones as A

BACKOFF = (2*3600, 6*3600, 24*3600, 72*3600)
FINAL = {'normal', 'overtime', 'penalties', 'retirement', 'walkover', 'dls', 'no_result', 'cancelled'}
MAX_EVENTS=1000
ALERT_RESERVE=200
CORRECTION_WINDOW=72*3600

DOMINANCE = {'Soccer': 3, 'Basketball': 20, 'Handball': 10, 'Ice Hockey': 4,
             'Rugby': 30, 'Field Hockey': 4, 'Lacrosse': 10, 'Softball': 8}


def de_historial(p, sport, source):
    """Sólo adaptadores que ya verificaron finalización; no inferirla desde puntos."""
    if p.get('tipo_estado') == 'pre':
        return None
    try:
        kickoff = U._parsear_iso(p.get('fecha', '')).timestamp()
        scores = [int(p['puntos_local']), int(p['puntos_visita'])]
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if min(scores) < 0 or kickoff >= time.time():
        return None
    names = [p.get('nom_local'), p.get('nom_visita')]
    if not all(names):
        return None
    return dict(A.contexto(dict(p, deporte=sport)), source=source,
                provider_id=p.get('id') or (('espn_' + str(p['_id'])) if source == 'espn' and p.get('_id') else None),
                provider_url=p.get('sportscore_url'), kickoff_utc=kickoff,
                kickoff_precision='date' if p.get('_fecha_solo_dia') else 'exact',
                participants=[U.firma_equipo(n) for n in names], participant_names=names,
                score=scores, status=p.get('_outcome_status', 'normal'),
                winner=U.firma_equipo(names[0 if scores[0] > scores[1] else 1]) if scores[0] != scores[1] else None,
                score_unit='sets' if sport == 'Volleyball' else 'points', set_points=p.get('puntos_por_set') or None, period_scope=p.get('_period_scope','unknown'),
                original_score=p.get('_original_score', scores), verified_at=time.time())


def compatible(event, outcome):
    if event.get('deporte') != outcome.get('sport'):
        return False
    names = [U.firma_equipo((event.get(l) or {}).get('nombre', '')) for l in ('local', 'visita')]
    if set(names) != set(outcome.get('participants', [])):
        return False
    obs = event.get('_observaciones') or [event]
    exact = any(o.get('fuente') == outcome.get('source') and (
        outcome.get('provider_id') and str(o.get('id')) == str(outcome['provider_id']) or
        outcome.get('provider_url') and o.get('sportscore_url') == outcome['provider_url']) for o in obs)
    # Aun con ID idéntico, verificar deporte y participantes antes de aceptar.
    ref=outcome.get('verified_event_ref') or {}
    if outcome.get('source') in ('lvf','lnv','tauron') and outcome.get('link_method')=='official_competition_alias_pair_exact_time':
        exact=exact or bool(ref.get('id') and ref.get('source')) and any(o.get('fuente')==ref.get('source') and o.get('id')==ref.get('id') and
                           o.get('startTimestamp')==outcome.get('kickoff_utc') for o in obs)
    if exact:
        return True
    ctx = A.contexto(event)
    if ctx['competition_id'] == 'unknown' or outcome.get('competition_id') in (None, 'unknown'):
        return False
    if A.serializar(ctx['competition_id']) != A.serializar(outcome['competition_id']):
        return False
    if ctx['season'] != outcome.get('season') or ctx['format'] != outcome.get('format') or ctx['category'] != outcome.get('category'):
        return False
    kickoff = event.get('startTimestamp')
    return bool(kickoff and outcome.get('kickoff_precision') == 'exact' and abs(kickoff-outcome.get('kickoff_utc', 0)) <= 3600)


def etiqueta(decision, outcome):
    result = {'definition_version': 'dominance-v1', 'status': outcome['status'], 'won': None, 'dominance': None}
    if outcome['status'] != 'normal':
        return result
    side = decision.get('favoured_participant_id')
    i = 0 if side in ('Local', 'local') else 1 if side in ('Visitante', 'visita') else None
    if i is None:
        return result
    fav = U.firma_equipo((decision.get('participants') or [{}, {}])[i].get('nombre', ''))
    result['won'] = outcome.get('winner') == fav if outcome.get('winner') else False
    sport = decision.get('sport')
    score = outcome.get('score')
    if sport in DOMINANCE and isinstance(score, list) and len(score) == 2:
        result['dominance'] = bool(result['won'] and abs(score[0]-score[1]) >= DOMINANCE[sport])
    elif sport == 'Volleyball' and isinstance(score, list):
        result['straight_sets'] = bool(result['won'] and sorted(score) == [0, 3])
        points=outcome.get('set_points')
        if points and all(isinstance(p,list) and len(p)==2 for p in points):
            names=outcome.get('participants') or []
            if fav in names:
                result['point_margin_for_favourite']=sum(a-b for a,b in points)*(1 if names.index(fav)==0 else -1)
        # Un 3-0 no acredita margen amplio de puntos.
    elif sport == 'Tennis' and outcome.get('sets'):
        sets = outcome['sets']
        result['dominance'] = bool(result['won'] and len(sets) == 2 and sum(abs(a-b) for a,b in sets) >= 8)
    elif sport == 'Cricket':
        result['dominance'] = bool(result['won'] and ((outcome.get('margin_unit') == 'wickets' and outcome.get('margin', 0) >= 7) or
            (outcome.get('margin_unit') == 'runs' and outcome.get('margin', 0) >= (40 if outcome.get('format') == 'T20' else 80))))
    return result


def _firma_resultado(row):
    names=row.get('participants') or []
    score=row.get('score')
    aligned=sorted(zip(names,score)) if isinstance(score,list) and len(names)==len(score) else None
    sets=row.get('sets')
    if sets and len(names)==2 and names[0]>names[1]:
        sets=[[b,a] for a,b in sets]
    return A.digest({'winner':row.get('winner'),'status':row.get('status'),'score':aligned,
                     'sets':sets,'margin':row.get('margin'),'margin_unit':row.get('margin_unit')})


class Resultados:
    def __init__(self, journal=None, clock=time.time):
        self.journal, self.clock = journal, clock
        self.data = U.cargar_json('resultados_evaluacion_v1.json', {})
        if not isinstance(self.data, dict):
            self.data = {}
        self.data.setdefault('tracked', {})
        self.data.setdefault('summary_days',{})
        self.data.setdefault('capacity',{'skipped':0,'non_alerts_replaced':0})
        self.dirty = False

    @staticmethod
    def _metricas(item):
        row={k:0 for k in ('tracked','alerts','resolved_alerts','normal_alerts_with_favourite',
                            'wins','losses_or_draws','dominance_evaluable','dominance','conflicts','expired')}
        row['tracked']=1
        row['conflicts']=int(item['state']=='conflict')
        row['expired']=int(item['state']=='expired')
        if item.get('decision')!='alert':return row
        row['alerts']=1
        if item['state']!='resolved':return row
        row['resolved_alerts']=1
        label=item.get('label') or {}
        if label.get('won') is not None:
            row['normal_alerts_with_favourite']=1
            row['wins']=int(label['won'])
            row['losses_or_draws']=int(not label['won'])
        if label.get('dominance') is not None:
            row['dominance_evaluable']=1
            row['dominance']=int(label['dominance'])
        return row

    def _retirar(self, key):
        item=self.data['tracked'].pop(key)
        day=datetime.fromtimestamp(item['event']['startTimestamp'],timezone.utc).date().isoformat()
        sports=self.data['summary_days'].setdefault(day,{})
        sport=item['event'].get('deporte','unknown')
        row=sports.setdefault(sport,{})
        for k,v in self._metricas(item).items():row[k]=row.get(k,0)+v
        self.dirty=True

    def mantener(self):
        now=self.clock()
        for key,item in list(self.data['tracked'].items()):
            age=now-item['event']['startTimestamp']
            if age>A.TTL:
                self.data['tracked'].pop(key);self.dirty=True
            elif (item['state']=='resolved' and age>CORRECTION_WINDOW and
                  now-item.get('resolved_at',0)>=6*3600) or item['state']=='expired':
                self._retirar(key)
        for day in list(self.data['summary_days']):
            if now-datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()>A.TTL:
                self.data['summary_days'].pop(day);self.dirty=True

    def seguir(self, ev, key, sid, decision, result=None):
        if not sid or not ev.get('startTimestamp') or ev['startTimestamp'] <= self.clock():
            return
        old = self.data['tracked'].get(key)
        if old:
            # La predicción alertada no se sustituye por un descarte posterior.
            if old.get('sid') != sid and not old.get('outcome') and old.get('decision')!='alert':
                old.update(sid=sid, decision=decision, favoured=(result or {}).get('favorito'),event=A.limpio(ev))
                self.dirty = True
            return
        self.mantener()
        tracked=self.data['tracked']
        full=len(tracked)>=MAX_EVENTS
        reserved=decision!='alert' and sum(t.get('decision')!='alert' for t in tracked.values())>=MAX_EVENTS-ALERT_RESERVE
        if full and decision=='alert':
            candidates=[(k,t) for k,t in tracked.items() if t.get('decision')!='alert' and t['state']=='pending']
            if candidates:
                victim=max(candidates,key=lambda pair:pair[1]['event']['startTimestamp'])[0]
                tracked.pop(victim)
                self.data['capacity']['non_alerts_replaced']+=1
                full=False
        if full or reserved:
            self.data['capacity']['skipped']+=1;self.dirty=True
            return
        tracked[key] = {'event': A.limpio(ev), 'sid': sid, 'decision': decision,
                        'next': ev['startTimestamp'] + BACKOFF[0], 'attempts': 0,
                        'state': 'pending', 'outcome': None, 'favoured':(result or {}).get('favorito')}
        self.dirty = True

    def incorporar(self, rows):
        rows=list(rows) # se reutiliza para cada partido, incluso si llega un generador
        journal = self.journal or A.diario()
        by_match={}
        for row in rows:
            if row and row.get('status') in FINAL:
                match=(row.get('sport'),tuple(sorted(row.get('participants') or [])))
                by_match.setdefault(match,[]).append(row)
        for key, item in self.data['tracked'].items():
            match=(item['event'].get('deporte'),tuple(sorted(U.firma_equipo((item['event'].get(l) or {}).get('nombre','')) for l in ('local','visita'))))
            found = [r for r in by_match.get(match,[]) if compatible(item['event'], r)]
            if not found:
                continue
            # Una fuente ausente este ciclo no elimina una contradicción ya observada.
            evidence=item.setdefault('source_results',{})
            refreshed={r['source'] for r in found}
            for old_key in list(evidence):
                if evidence[old_key].get('source') in refreshed:evidence.pop(old_key)
            for row in found:evidence[row['source']+'|'+_firma_resultado(row)]=row
            found=list(evidence.values())
            signatures = {_firma_resultado(r) for r in found}
            if len(signatures) != 1:
                conflict={'outcome_key':key,'sport':item['event'].get('deporte'),'status':'conflict','conflict':True,
                          'source_results':found,'verified_at':self.clock()}
                conflict_sid=journal.guardar('outcome',conflict, material={'status':'conflict','signatures':sorted(signatures)})
                item['outcome']=conflict_sid
                item['state'] = 'conflict'
                item['conflict_sources'] = sorted({r['source'] for r in found})
                self.dirty = True
                continue
            outcome = dict(found[0], outcome_key=key, confirming_sources=sorted({r['source'] for r in found}))
            material = {k: v for k,v in outcome.items() if k != 'verified_at'}
            sid = journal.guardar('outcome', outcome, material=material)
            if not sid:
                continue
            decision={'sport':item['event'].get('deporte'),'participants':[item['event'].get(l) or {} for l in ('local','visita')],
                      'favoured_participant_id':item.get('favoured')}
            item.update(outcome=sid, state='resolved', label=etiqueta(decision,outcome))
            item.setdefault('resolved_at',self.clock())
            self.dirty = True

    def recoger(self, modules, max_groups=8):
        self.mantener()
        now = self.clock()
        event_queries=0
        pendientes = [(k,t) for k,t in self.data['tracked'].items() if t['next'] <= now and t['state'] != 'expired'
                       and (not t.get('checked') or now-t['checked'] >= 6*3600)]
        # Resueltos se revisan durante 72 horas por correcciones, sin reescribir si nada cambió.
        pendientes = [(k,t) for k,t in pendientes if t['state'] != 'resolved' or now-t['event']['startTimestamp'] <= 72*3600]
        groups = {}
        for key, item in pendientes:
            ev = item['event']
            group = (ev.get('deporte'), A.serializar(A.contexto(ev)['competition_id'] if A.contexto(ev)['competition_id']!='unknown' else ev.get('torneo')), datetime.fromtimestamp(ev['startTimestamp'], timezone.utc).date().isoformat())
            groups.setdefault(group, []).append((key, item))
        for group, items in sorted(groups.items(), key=lambda g: (
                not any(t.get('decision')=='alert' and t['state']!='resolved' for _,t in g[1]),
                min(t.get('checked',0) for _,t in g[1]),min(t['next'] for _,t in g[1])))[:max_groups]:
            rows = []
            ev = dict(items[0][1]['event'])
            ev['_observaciones']=[o for _,item in items for o in item['event'].get('_observaciones') or [item['event']]]
            for source, module in modules.items():
                if not module or not hasattr(module, 'resultados_evaluacion'):
                    continue
                try:
                    if source in ('sportsapi_app','lvf','lnv','tauron'):
                        ordered=sorted(items,key=lambda pair:(pair[1].get('decision')!='alert',pair[1].get('event_checked',0)))
                        for _,item in ordered:
                            if source=='sportsapi_app':
                                if event_queries>=8:break
                                if not any(o.get('fuente')==source for o in item['event'].get('_observaciones') or [item['event']]):continue
                                event_queries+=1
                                item['event_checked']=now
                            rows.extend(module.resultados_evaluacion(item['event']) or [])
                    else:
                        rows.extend(module.resultados_evaluacion(ev) or [])
                except Exception as exc:
                    U.log('[outcomes/' + source + '] ' + type(exc).__name__)
            self.incorporar(rows)
            for _, item in items:
                has_app=any(o.get('fuente')=='sportsapi_app' for o in item['event'].get('_observaciones') or [item['event']])
                if has_app and 'sportsapi_app' in modules and item.get('event_checked')!=now and item['state']!='resolved':
                    # La cota de consultas por ID no equivale a una búsqueda fallida.
                    item['next']=now+900
                    self.dirty=True
                    continue
                item['checked'] = now
                item['attempts'] += 1
                item['next'] = now + BACKOFF[min(item['attempts'], len(BACKOFF)-1)]
                if now - item['event']['startTimestamp'] > 30*86400 and item['state']!='resolved':
                    item['state'] = 'expired'
                self.dirty = True
        self.mantener()

    def guardar(self):
        if self.dirty:
            ok = U.guardar_json('resultados_evaluacion_v1.json', self.data)
            self.dirty = not ok

    def estado(self):
        states = {}
        for item in self.data['tracked'].values():
            states[item['state']] = states.get(item['state'], 0)+1
        sports={}
        for day in self.data['summary_days'].values():
            for sport,metrics in day.items():
                row=sports.setdefault(sport,{})
                for k,v in metrics.items():row[k]=row.get(k,0)+v
        for item in self.data['tracked'].values():
            row=sports.setdefault(item['event'].get('deporte','unknown'),{})
            for k,v in self._metricas(item).items():row[k]=row.get(k,0)+v
        for row in sports.values():
            n=row.get('normal_alerts_with_favourite',0)
            row['win_rate']=row.get('wins',0)/n if n else None
            row['resolved_non_normal_alerts']=row.get('resolved_alerts',0)-n
            row['unresolved_alerts']=row.get('alerts',0)-row.get('resolved_alerts',0)
        return {'tracked_events':len(self.data['tracked']),'states':states,'retention_days':90,'max_events':MAX_EVENTS,
                'alert_reserved_slots':ALERT_RESERVE,'capacity':dict(self.data['capacity']),
                'summary_days':len(self.data['summary_days']),'correction_window_hours':72,
                'sports':sports,'metrics_scope':'active follow-up plus rolling 90-day retired summaries; not permanent archive',
                'states_scope':'active follow-up only; sports metrics include rolling summaries',
                'prediction_scope':'first recorded alert per event; final sporting result; period scope can be unknown'}


_actual = None

def actual():
    global _actual
    if _actual is None:
        _actual = Resultados()
    return _actual
