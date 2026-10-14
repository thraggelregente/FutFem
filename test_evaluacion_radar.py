"""Contratos de integridad, temporalidad, identidad y bolsas compartidas."""
import copy
import json
import tempfile
import unittest
from unittest.mock import patch, Mock
import auditoria_decisiones as A
import cobertura_radar as C
import resultados_evaluacion as R
import planificador_datos as P
import evaluacion_motor as E
import fuente_tennis_api as T
import utilidades as U


def event(ts=2000000000, sport='Soccer'):
    return {'id':'fixture1','fuente':'unit','deporte':sport,'torneo':'Women League','femenino_seguro':True,
            'contexto_competicion':'league:1','season_ref':2026,'tipo_estado':'pre','startTimestamp':ts,
            'local':{'id':'a','nombre':'A Women'},'visita':{'id':'b','nombre':'B Women'}}


class DiarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.object(U,'DATA_DIR',self.tmp.name)
        self.env.start()
        self.cloud=patch.object(U,'usa_upstash',return_value=False)
        self.cloud.start()
        self.now=[1000]
        self.diary=A.Diario(clock=lambda:self.now[0])

    def tearDown(self):
        self.env.stop();self.cloud.stop();self.tmp.cleanup()

    def test_immutable_idempotent_with_shared_evidence(self):
        value={'event_key':'e','decision':'discard'}
        sid=self.diary.guardar('decision',value,{'history':[1,2]})
        self.now[0]+=60
        self.assertEqual(sid,self.diary.guardar('decision',value,{'history':[1,2]}))
        changed=self.diary.guardar('decision',dict(value,decision='alert'),{'history':[1,2]})
        self.assertNotEqual(sid,changed)
        self.assertEqual(len(self.diary.index['objects']),3)
        self.diary.flush()
        self.assertEqual(self.diary.leer(sid)['record']['decision'],'discard')
        self.assertEqual(self.diary.estado()['persistence'],'volatile')
        self.assertEqual(len(list(self.diary.registros())),2)

    def test_clock_only_change_does_not_create_another_snapshot(self):
        record={'event_key':'a','decision':'discard'}
        sid=self.diary.guardar('decision',record,{'inputs':{'evaluation_at_utc':1000,'history':[1]}})
        self.now[0]+=900
        again=self.diary.guardar('decision',record,{'inputs':{'evaluation_at_utc':1900,'history':[1]}})
        self.assertEqual(sid,again)
        self.assertNotEqual(sid,self.diary.guardar('decision',record,{'inputs':{'evaluation_at_utc':1900,'history':[2]}}))

    def test_capacity_does_not_evict_referenced_evidence(self):
        with patch.object(A,'MAX_RECORDS',2):
            self.assertIsNotNone(self.diary.guardar('decision',{'event_key':'a'},{'large':'x'}))
            self.assertIsNone(self.diary.guardar('decision',{'event_key':'b'},{'large':'x'}))
        self.assertEqual(self.diary.omitted,1)

    def test_expiration_prunes_index(self):
        self.diary.guardar('decision',{'event_key':'a'},{'history':[]})
        self.now[0]+=A.TTL+1
        self.diary._prune()
        self.assertEqual(self.diary.index['objects'],{})

    def test_secrets_removed_recursively(self):
        data=A.limpio({'authorization':'secret','history':[{'odds':2,'score':3,'chat_id':123}],'api_key':'secret'})
        self.assertEqual(data,{'history':[{'score':3}]})

    def test_json_error_http200_is_not_success(self):
        response=Mock();response.json.return_value={'error':'ERR max memory'}
        with patch.object(U.requests,'post',return_value=response):
            with self.assertRaises(ValueError): U._upstash(['SET','k','v'])
        self.assertFalse(U._UPSTASH_ULTIMO_OK)

    def test_pipeline_partial_error_does_not_claim_complete_success(self):
        response=Mock();response.json.return_value=[{'result':'OK'},{'error':'ERR memory'}]
        with patch.object(U.requests,'post',return_value=response):
            self.assertEqual(U._upstash_pipeline([['SET','a','1'],['SET','b','2']]),[True,False])
        self.assertFalse(U._UPSTASH_ULTIMO_OK)

    def test_redis_errors_keep_pending_and_report_failure(self):
        self.diary.guardar('decision',{'event_key':'a'})
        with patch.object(U,'usa_upstash',return_value=True), patch.object(U,'_upstash',side_effect=ValueError('ERR')), patch.object(U,'_upstash_pipeline',side_effect=ValueError('ERR')):
            self.diary.flush()
        self.assertTrue(self.diary.pending)
        self.assertEqual(self.diary.persistence,'failed')


class CoverageTests(unittest.TestCase):
    def test_three_sources_one_event_and_latest_reason_only(self):
        coverage=C.Cobertura()
        ev=event();ev['_fuentes_detectadas']=['one','two','three']
        for source in ev['_fuentes_detectadas']:
            coverage.consulta(source,'Soccer',1)
        coverage.evento('e',ev)
        coverage.decision('e','unevaluable','missing')
        coverage.decision('e','alert','threshold',{'puntaje':4})
        report=coverage.resumen()
        self.assertEqual(sum(report['normalized_observations'].values()),3)
        self.assertEqual(report['sports']['Soccer']['unique_events'],1)
        self.assertEqual(report['sports']['Soccer']['states'],{'alert:threshold':1})
        self.assertIsNone(report['coverage_percentage'])

    def test_deliveries_are_per_role(self):
        c=C.Cobertura();c.entrega('personal',True);c.entrega('group',False)
        self.assertEqual(c.resumen()['deliveries_by_role'],{'personal:complete':1,'group:failed':1})


class OutcomeTests(unittest.TestCase):
    def test_visitor_wins_is_oriented_by_name(self):
        d={'sport':'Soccer','participants':[event()['local'],event()['visita']],'favoured_participant_id':'Visitante'}
        o={'sport':'Soccer','status':'normal','winner':U.firma_equipo('B Women'),'score':[0,4]}
        label=R.etiqueta(d,o)
        self.assertTrue(label['won']);self.assertTrue(label['dominance'])

    def test_retirement_does_not_count_as_defeat(self):
        d={'sport':'Tennis','participants':[{},{}],'favoured_participant_id':'Local'}
        self.assertIsNone(R.etiqueta(d,{'status':'retirement'})['won'])

    def test_volleyball_sets_do_not_prove_point_margin(self):
        d={'sport':'Volleyball','participants':[event()['local'],event()['visita']],'favoured_participant_id':'Local'}
        label=R.etiqueta(d,{'status':'normal','winner':U.firma_equipo('A Women'),'score':[3,0]})
        self.assertTrue(label['straight_sets']);self.assertIsNone(label['dominance'])

    def test_identity_not_just_names_and_day(self):
        ev=event()
        o={'sport':'Soccer','source':'unit','provider_id':'fixture1','participants':[U.firma_equipo('A Women'),U.firma_equipo('B Women')]}
        self.assertTrue(R.compatible(ev,o))
        self.assertFalse(R.compatible(dict(ev,id='fixture2'),o))
        self.assertFalse(R.compatible(ev,dict(o,sport='Softball')))

    def test_grouped_fetch_and_backoff(self):
        clock=lambda:2000000000
        journal=Mock();journal.guardar.return_value='outcome'
        with patch.object(U,'cargar_json',return_value={}):
            results=R.Resultados(journal,clock)
        ev=event(2000000000-10000)
        results.data['tracked']={'a':{'event':ev,'sid':'s','state':'pending','next':0,'attempts':0,'outcome':None},
                                'b':{'event':dict(ev,id='other'),'sid':'s','state':'pending','next':0,'attempts':0,'outcome':None}}
        module=Mock();module.resultados_evaluacion.return_value=[]
        results.recoger({'unit':module})
        self.assertEqual(module.resultados_evaluacion.call_count,1)
        self.assertEqual(results.data['tracked']['a']['next'],clock()+6*3600)
        results.recoger({'unit':module})
        self.assertEqual(module.resultados_evaluacion.call_count,1)

    def test_conflicting_results_remain_conflict(self):
        j=Mock();j.guardar.return_value='s'
        with patch.object(U,'cargar_json',return_value={}):r=R.Resultados(j)
        ev=event(2000)
        r.data['tracked']['a']={'event':ev,'sid':'s','state':'pending','outcome':None}
        base={'sport':'Soccer','source':'unit','provider_id':'fixture1','participants':[U.firma_equipo('A Women'),U.firma_equipo('B Women')],
              'status':'normal','winner':U.firma_equipo('A Women'),'score':[4,0]}
        r.incorporar([base,dict(base,score=[3,0])])
        self.assertEqual(r.data['tracked']['a']['state'],'conflict')


class PlannerTests(unittest.TestCase):
    def test_shared_sportscore_budget_and_dedup(self):
        p=P.Planificador()
        tasks=[{'source':'sportscore','key':k,'deadline':200,'cost':1} for k in ('tennis','basket','tennis')]
        selected=p.seleccionar(tasks,{'sportscore':1},now=100)
        self.assertEqual(len(selected),1)

    def test_expired_cached_paused_tasks_are_not_selected(self):
        p=P.Planificador();p.http('source',403,now=100)
        tasks=[{'source':'source','key':'one','deadline':200}, {'source':'other','key':'two','deadline':90},
               {'source':'other','key':'three','deadline':200,'cache_valid':True}]
        self.assertEqual(p.seleccionar(tasks,{'source':100,'other':100},now=100),[])

    def test_unknown_cases_get_exploration_slots(self):
        p=P.Planificador()
        tasks=[{'source':'s','key':str(i),'deadline':200,'missing':True} for i in range(10)]+[{'source':'s','key':'unknown','deadline':200,'new_coverage':True}]
        selected=p.seleccionar(tasks,{'s':100},now=100,limit=5)
        self.assertIn('unknown',[t['key'] for t in selected])


class TemporalTests(unittest.TestCase):
    def test_future_history_rejected(self):
        s={'observed_at_utc':100,'kickoff_utc':200,'pre_match':True,'evidence':{'inputs':{'history':[{'ts':101}]}}}
        with self.assertRaisesRegex(ValueError,'future_information'):E.validar_asof(s)

    def test_postmatch_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError,'not_pre_match'):E.validar_asof({'observed_at_utc':100,'kickoff_utc':90,'pre_match':False})

    def test_empty_dataset_has_no_fake_accuracy(self):
        report=E.evaluar([],{})
        self.assertEqual(report['sports'],{})
        self.assertFalse(report['old_ledger_imported'])

    def test_replay_tennis_uses_frozen_time_and_profiles(self):
        ev=event(2000,'Tennis');ev['local']['ranking']=10;ev['visita']['ranking']=900
        import motor_tenis
        result=motor_tenis.evaluar(ev,{},ahora=1000)
        s={'sport':'Tennis','observed_at_utc':1000,'kickoff_utc':2000,'pre_match':True,
           'evidence':{'event':ev,'inputs':{'perfiles':{},'evaluation_at_utc':1000},'result':result}}
        self.assertEqual(E.replay(s),result)


class TennisApiTests(unittest.TestCase):
    def test_allowlist_strips_legacy_odds(self):
        raw={'id':1,'odd1':1.02,'links':{'odds':'url'},'player1':{'id':1,'name':'One','odds':2},'tournament':{'id':1,'name':'Women'}}
        data=T.factual(raw)
        self.assertNotIn('odd1',data);self.assertNotIn('links',data);self.assertNotIn('odds',data['player1'])

    def test_missing_time_not_alerted_and_wc_third_party(self):
        now=2000000000
        stamp=datetime_iso(now+3600)
        raw={'id':1,'startTime':stamp,'player1':{'id':1,'name':'Anna Player'},'player2':{'id':2,'name':'Betty Player'},
             'seed2':'WC','tournament':{'id':9,'date':stamp,'name':'Women Tournament','court':{'name':'Hard'}}}
        normal=T.normalizar(raw,now)
        self.assertEqual(normal['visita']['entry_fuente'],'Tennis API (tercero)')
        self.assertIsNone(T.normalizar(dict(raw,startTime=None,date=None),now))


def datetime_iso(ts):
    from datetime import datetime,timezone
    return datetime.fromtimestamp(ts,timezone.utc).isoformat()


if __name__=='__main__':unittest.main()

class IntegrationTests(unittest.TestCase):
    def test_motor_signals_preserve_points_and_replay(self):
        import motor_mismatches as M
        kwargs={'deporte':'Soccer','perf_local':M.evaluar_rendimiento_reciente([], 'a', 'Soccer'),'perf_visita':M.evaluar_rendimiento_reciente([], 'b', 'Soccer'),'triangulaciones':[], 'h2h':{},
                'tabla_local_visita':{'es_mismatch_tabla':True,'favorito':'Local','detalle':'table'},'datos_extra':{}}
        result=M.evaluar_mismatch(**kwargs)
        self.assertEqual(result['signals'][0]['effective_points'],2)
        d={'sport':'Soccer','observed_at_utc':100,'kickoff_utc':200,'pre_match':True,
           'evidence':{'inputs':{'motor_kwargs':kwargs},'result':result}}
        self.assertEqual(E.replay(d),result)

    def test_conflict_normalization_handles_reversed_participants(self):
        a,b=U.firma_equipo('A Women'),U.firma_equipo('B Women')
        row={'winner':a,'status':'normal','participants':[a,b],'score':[4,0]}
        self.assertEqual(R._firma_resultado(row),R._firma_resultado(dict(row,participants=[b,a],score=[0,4])))

    def test_snapshot_retains_inputs_and_metrics_exclude_unresolved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(U,'DATA_DIR',directory), patch.object(U,'usa_upstash',return_value=False):
            diary=A.Diario(clock=lambda:1000)
            sid=diary.guardar('decision',{'event_key':'a','decision':'alert'},{'inputs':{'sample':[1]}})
            results=R.Resultados(diary,clock=lambda:1000)
            results.seguir(event(2000),'a',sid,'alert',{'favorito':'Local'})
            self.assertEqual(results.estado()['sports']['Soccer']['normal_alerts_with_favourite'],0)
            self.assertEqual(list(diary.registros())[0]['evidence']['inputs'],{'sample':[1]})

    def test_source_map_does_not_count_disabled_or_tennis_context_tsdb(self):
        import mapa_fuentes
        espn=Mock();espn._ligas_configuradas.return_value={'Soccer':{},'Tennis':{},'Softball':{}}
        tsdb=Mock();tsdb.disponible.return_value=True;tsdb.historial_disponible.return_value=True;tsdb._LIGAS_FEMENINAS={'Soccer':set(['1'])}
        api=Mock();api.disponible.return_value=False
        m=mapa_fuentes.construir({'espn':espn,'thesportsdb':tsdb,'api_football':api})
        self.assertEqual(m['sports']['Tennis']['configured_sources'],['espn'])
        self.assertEqual(m['sports']['Softball']['configured_sources'],['espn'])
        self.assertIn('thesportsdb',m['sports']['Handball']['context_only_sources'])
