"""CLI offline: replay inmutable, bloques temporales y comparación sobre el mismo universo.

python evaluacion_motor.py --input export.jsonl --gap-days 7 --block-days 28
python evaluacion_motor.py --export export.jsonl  # lee el diario configurado; no consulta proveedores
"""
import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
import auditoria_decisiones as A
import resultados_evaluacion as R


CONFIG = {sport: {'version': 'shadow-v1', 'threshold': threshold} for sport, threshold in
          [('Soccer',5), ('Basketball',5), ('Handball',5), ('Volleyball',5), ('Ice Hockey',5),
           ('Rugby',5), ('Softball',6), ('Lacrosse',6), ('Field Hockey',6), ('Tennis',4), ('Cricket',None)]}


def validar_asof(snapshot):
    when = snapshot.get('observed_at_utc')
    if not isinstance(when, (int,float)) or not snapshot.get('pre_match') or when >= snapshot.get('kickoff_utc',0):
        raise ValueError('not_pre_match')
    inputs = (snapshot.get('evidence') or {}).get('inputs') or {}
    def visit(value):
        if isinstance(value, dict):
            for key,item in value.items():
                if key in ('ts', 'observed_at_utc', 'verified_at', 'known_at') and isinstance(item, (int,float)) and item > when:
                    raise ValueError('future_information')
                if key == 'fecha' and isinstance(item,str):
                    try:
                        t = datetime.fromisoformat(item.replace('Z','+00:00'))
                        if t.tzinfo and t.timestamp() > when:
                            raise ValueError('future_information')
                    except ValueError as exc:
                        if str(exc) == 'future_information':
                            raise
                visit(item)
        elif isinstance(value,list):
            for item in value:
                visit(item)
    visit(inputs)
    return inputs


def replay(snapshot):
    inputs = validar_asof(snapshot)
    sport = snapshot['sport']
    if sport == 'Tennis':
        import motor_tenis
        return motor_tenis.evaluar(snapshot['evidence']['event'], inputs.get('perfiles'), ahora=inputs.get('evaluation_at_utc',snapshot['observed_at_utc']))
    if sport == 'Cricket':
        import motor_cricket
        return motor_cricket.evaluar(snapshot['evidence']['event'], inputs.get('registros', []), inputs.get('evaluation_at_utc',snapshot['observed_at_utc']))
    import motor_mismatches
    if 'motor_kwargs' not in inputs:
        raise ValueError('missing_frozen_inputs')
    return motor_mismatches.evaluar_mismatch(**inputs['motor_kwargs'])


def baseline(snapshot):
    if snapshot['sport'] == 'Tennis':
        ranks = [p.get('ranking') for p in snapshot['participants']]
        if all(isinstance(r,int) and r>0 for r in ranks) and ranks[0] != ranks[1]:
            return 'Local' if ranks[0]<ranks[1] else 'Visitante'
    elo = (((snapshot.get('evidence') or {}).get('inputs') or {}).get('motor_kwargs') or {}).get('datos_extra', {}).get('elo')
    return (elo or {}).get('favorito')


def sombra(snapshot):
    sport = snapshot['sport']
    score = snapshot.get('score')
    cfg = CONFIG.get(sport, {'threshold':None})
    if cfg['threshold'] is None:
        return snapshot.get('decision') == 'alert'
    # Regla candidata: contexto documentado y mayor umbral; jamás cambiar producción desde aquí.
    inputs = ((snapshot.get('evidence') or {}).get('inputs') or {})
    if sport == 'Tennis':
        profiles = inputs.get('perfiles') or {}
        if not all(p and len(p.get('recientes',[])) >=4 for p in profiles.values()) or len(profiles)!=2:
            return False
    return isinstance(score,(int,float)) and score >= cfg['threshold']


def wilson(wins, n):
    if not n:
        return None
    z=1.96
    center=(wins/n+z*z/(2*n))/(1+z*z/n)
    radius=z*math.sqrt(wins/n*(1-wins/n)/n+z*z/(4*n*n))/(1+z*z/n)
    return [round(max(0,center-radius),4),round(min(1,center+radius),4)]


def evaluar(decisions, outcomes, gap_days=7, block_days=28):
    if gap_days < 0 or block_days < 1:
        raise ValueError('invalid_calendar_blocks')
    latest = {}
    for decision in decisions:
        if decision.get('decision') not in ('alert','discard','candidate','unevaluable') or not decision.get('pre_match'):
            continue
        old = latest.get(decision['event_key'])
        # Una predicción por encuentro: la última capturada antes del comienzo.
        if old is None or decision['observed_at_utc'] > old['observed_at_utc']:
            latest[decision['event_key']] = decision
    dates = sorted(d['observed_at_utc'] for d in latest.values())
    origin = (dates[0]//86400)*86400 if dates else 0
    stats = defaultdict(lambda: {'events':0,'resolved':0,'normal':0,'live_alerts':0,'live_wins':0,
                                 'shadow_alerts':0,'shadow_wins':0,'baseline_eligible':0,'baseline_wins':0,'paired_alerts':0,'paired_live_wins':0,'paired_baseline_wins':0,'dominated':0,
                                 'dominance_evaluable':0,'unresolved':0,'replay_errors':0,'replay_eligible':0,'unfavoured_decisions':0})
    blocks = defaultdict(lambda: {'events':0,'resolved':0,'live_alerts':0,'wins':0})
    for key, d in latest.items():
        s=stats[d['sport']]
        s['events']+=1
        period=int((d['observed_at_utc']-origin)//(block_days*86400))
        block=blocks[(d['sport'],period)]
        block['events']+=1
        inputs=((d.get('evidence') or {}).get('inputs') or {})
        engine_evaluated=any(k in inputs for k in ('motor_kwargs','perfiles','registros'))
        try:
            if not engine_evaluated:
                result=(d.get('evidence') or {}).get('result') or {}
            else:
                s['replay_eligible']+=1
                result=replay(d)
            recorded=(d.get('evidence') or {}).get('result') or {}
            if A.digest(result)!=A.digest(recorded):
                raise ValueError('replay_mismatch')
        except (ValueError, KeyError, TypeError):
            s['replay_errors']+=1
        o=outcomes.get(key)
        if not o or o.get('conflict'):
            s['unresolved']+=1
            continue
        s['resolved']+=1
        block['resolved']+=1
        label=R.etiqueta(d,o)
        if label['status']!='normal':
            continue
        s['normal']+=1
        is_alert=d['decision']=='alert'
        if is_alert:
            s['live_alerts']+=1
            s['live_wins']+=int(label['won'] is True)
            block['live_alerts']+=1
            block['wins']+=int(label['won'] is True)
            if label['dominance'] is not None:
                s['dominance_evaluable']+=1
                s['dominated']+=int(label['dominance'])
        if d.get('favoured_participant_id') is None:
            s['unfavoured_decisions']+=1
        if sombra(d):
            s['shadow_alerts']+=1
            s['shadow_wins']+=int(label['won'] is True)
        side=baseline(d)
        if side:
            s['baseline_eligible']+=1
            baseline_label=R.etiqueta(dict(d,favoured_participant_id=side),o)
            s['baseline_wins']+=int(baseline_label['won'] is True)
            if is_alert:
                s['paired_alerts']+=1
                s['paired_live_wins']+=int(label['won'] is True)
                s['paired_baseline_wins']+=int(baseline_label['won'] is True)
    for s in stats.values():
        s['live_win_wilson_95']=wilson(s['live_wins'],s['live_alerts'])
        s['resolved_fraction']=s['resolved']/s['events'] if s['events'] else None
    calendar_blocks=[]
    for (sport,period),row in sorted(blocks.items()):
        start=origin+period*block_days*86400
        cutoff=start-gap_days*86400
        train=[d for d in latest.values() if d['sport']==sport and d['observed_at_utc']<cutoff and
               d.get('kickoff_utc',float('inf'))+72*3600<cutoff and
               outcomes.get(d['event_key'],{}).get('verified_at',float('inf'))<cutoff]
        calendar_blocks.append(dict(row,sport=sport,start_utc=start,train_cutoff_utc=cutoff,
                                    preceding_training_events=len(train)))
    return {'mode':'prospective_descriptive_and_shadow; no_auto_tuning', 'rules':CONFIG,
            'sports':dict(stats), 'calendar_blocks':calendar_blocks, 'gap_days':gap_days,
            'minimum_validation_note':'Las reglas candidatas están fijadas. No hay ajuste ni probabilidad calibrada; métricas con denominadores distintos no son comparables.',
            'old_ledger_imported':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input')
    parser.add_argument('--export')
    parser.add_argument('--gap-days',type=int,default=7)
    parser.add_argument('--block-days',type=int,default=28)
    args=parser.parse_args()
    if args.export:
        journal=A.diario()
        with open(args.export,'w',encoding='utf-8') as f:
            for tipo in ('decision','outcome'):
                for record in journal.registros(tipo):
                    f.write(A.serializar({'type':tipo,'record':record})+'\n')
        journal.flush()
        return
    if not args.input:
        parser.error('--input o --export requerido')
    with open(args.input,encoding='utf-8') as f:
        rows=[json.loads(line) for line in f if line.strip()]
    decisions=[r['record'] for r in rows if r['type']=='decision']
    outcomes={}
    for row in rows:
        if row['type']=='outcome':
            record=row['record']
            old=outcomes.get(record['outcome_key'])
            if old is None or record['observed_at_utc']>old['observed_at_utc']:
                outcomes[record['outcome_key']]=record
    print(json.dumps(evaluar(decisions,outcomes,args.gap_days,args.block_days),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
