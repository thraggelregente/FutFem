"""Regresiones del aprovechamiento: cuotas, identidad, caducidad y seguimiento."""
import test_radar
from test_radar import evento,partido
from test_sportsapi_app import raw
import copy
import tempfile
import time
import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch,Mock
import utilidades as U
import fuente_sportsapi_app as S
import resultados_evaluacion as R
import evaluacion_motor as E
import main as B
from voley_oficial import Oficial,cargar_lvf,cargar_lnv,completar_lnv,temporada_actual


class PacingTests(unittest.TestCase):
    def test_cuota_gradual_y_completa_a_fin_del_dia(self):
        self.assertEqual(S._allowance(100,12,0),12)
        self.assertEqual(S._allowance(100,12,12*3600),57)
        self.assertEqual(S._allowance(100,12,23*3600),100)
        self.assertEqual(S._allowance(40,6,23*3600),40)

    def test_ritmo_conserva_cache_sin_gastar_y_no_reinicia_con_proceso(self):
        cached={'data':[]}
        quota=SimpleNamespace(usadas=25,restantes=lambda:75)
        with patch.object(S,'disponible',return_value=True),patch.object(S,'presupuesto',quota), \
             patch.object(S,'_allowance',return_value=20),patch.object(S._cache,'get',return_value=(True,cached)), \
             patch.object(S.requests,'get') as get:
            self.assertEqual(S._get('/v2/fixtures',calendar=True,refresh=True),cached)
            get.assert_not_called()

    def test_actualiza_cabecera_antes_de_profundizar(self):
        state={'cursors':{'Volleyball|'+S._day():5}}
        response={'data':[],'meta':{'sport':'volleyball','date':S._day(),'page':0,'hasNextPage':True}}
        with patch.object(S,'disponible',return_value=True),patch.object(S,'_catalogo',return_value={'volleyball'}), \
             patch.object(S,'_state',state),patch.object(S,'_save'),patch.object(S,'_get',return_value=response) as get:
            S.obtener_eventos('Volleyball')
        self.assertTrue(all(c.args[1]['page']==0 and c.kwargs['refresh'] for c in get.call_args_list))

    def test_contadores_unicos_no_cuentan_repeticiones(self):
        with patch.object(S,'_unique',{k:set() for k in S._unique}):
            S._unique_add('calendar',['one','two']);S._unique_add('calendar',['one'])
            self.assertEqual(S.estado_contexto()['unique_observed']['calendar'],2)
            self.assertIn('repeated',S.estado_contexto()['metrics_scope'])

    def test_resultado_usa_observacion_secundaria_por_id(self):
        obs=S.normalizar(raw(),'Volleyball');event=copy.deepcopy(obs)
        event.update(fuente='oddspapi',id='other',_observaciones=[obs])
        with patch.object(S,'_get',return_value={'data':raw(finished=True)}) as get:
            self.assertEqual(len(S.resultados_evaluacion(event)),1)
        self.assertEqual(get.call_args.args[0],'/v2/fixtures/101')


    def test_refresco_fallido_preserva_cache_y_espera_una_hora(self):
        cached={'data':[]}
        quota=SimpleNamespace(usadas=0,restantes=lambda:100,puede_gastar=lambda:True,registrar=lambda:None)
        with patch.object(S,'disponible',return_value=True),patch.object(S,'_state',{}),patch.object(S,'_save'), \
             patch.object(S,'_pausa',0),patch.object(S.P.actual,'permitido',return_value=True), \
             patch.object(S,'presupuesto',quota),patch.object(S._ritmo,'esperar'), \
             patch.object(S._cache,'get',return_value=(True,cached)),patch.object(S._cache,'set') as cache, \
             patch.object(S.requests,'get',side_effect=S.requests.RequestException) as get:
            self.assertEqual(S._get('/v2/fixtures',refresh=True),cached)
            self.assertEqual(S._get('/v2/fixtures',refresh=True),cached)
            self.assertEqual(get.call_count,1);cache.assert_not_called()


class ContextTests(unittest.TestCase):
    def test_respaldo_aislado_remapea_y_no_suma_muestras(self):
        event=evento();event.update(fuente='sportscore',historial_aislado=True,torneo='League Women')
        obs=copy.deepcopy(event);obs.update(fuente='sportsapi_app',id='second')
        obs['local']['id']='sapp:a';obs['visita']['id']='sapp:b'
        event['_observaciones']=[dict(event),obs]
        hist=[partido('sapp:a','sapp:b',dias=i+1) for i in range(4)]
        with patch.object(B,'_contextos_oficiales',return_value=[]), \
             patch.object(B,'fuente_sportscore',SimpleNamespace(historial_equipo=lambda *a:[])), \
             patch.object(B,'fuente_sportsapi_app',SimpleNamespace(historial_equipo=lambda *a:hist)):
            rows=B._historial_equipo(event,'local')
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]['id_local'],event['local']['id'])
        self.assertEqual(rows[0]['id_visita'],event['visita']['id'])

    def test_respaldo_rechaza_otra_liga_temporada_y_hora(self):
        ev=evento();ev.update(torneo='League Women',season_ref=2026,season_label=2026)
        for diff in ({'torneo':'Cup Women'},{'season_ref':2025,'season_label':2025},{'startTimestamp':ev['startTimestamp']+7200}):
            obs=dict(ev,fuente='sportsapi_app',**diff)
            self.assertFalse(B._respaldo_compatible(ev,obs))

    def test_cooldown_se_abre_solo_con_cambio_relevante(self):
        ev=evento();key='event';stamp=B._firma_contexto(ev)
        with patch.object(B,'_enfriamiento',{key:(2000,2)}),patch.object(B,'_contexto_intento',{key:stamp}):
            self.assertTrue(B._en_enfriamiento(key,1000,ev))
            ev['_observaciones']=[dict(ev,fuente='sportsapi_app')]
            self.assertFalse(B._en_enfriamiento(key,1000,ev))
            B._contexto_intento[key]=B._firma_contexto(ev)
            B._enfriamiento[key]=(2000,1)
            self.assertTrue(B._en_enfriamiento(key,1000,ev))

    def test_cooldown_orden_de_fuentes_no_es_dato_nuevo(self):
        ev=evento();ev['_observaciones']=[dict(ev),dict(ev,fuente='sportsapi_app')]
        signature=B._firma_contexto(ev)
        ev['_observaciones'].reverse()
        self.assertEqual(signature,B._firma_contexto(ev))


class FreshnessTests(unittest.TestCase):
    def official(self,source='lvf'):
        o=Oficial(source);o.tabla={'a':{'nombre':'A'},'b':{'nombre':'B'}}
        o.edicion='lvf:a1:'+temporada_actual() if source=='lvf' else 'lnv:d1f:123'
        o.last_verified=time.time()-3600
        o.historial=[{'id':'verified'}]
        return o

    def test_cuota_o_red_no_borran_contexto_vigente(self):
        o=self.official()
        with patch.object(o.cliente,'pedir',return_value=None):cargar_lvf(o)
        self.assertEqual(o.historial,[{'id':'verified'}])
        self.assertEqual(o.status['state'],'last_valid_context')
        self.assertTrue(o._vigente())

    def test_caduca_y_no_cruza_temporada(self):
        o=self.official();o.last_verified=time.time()-49*3600
        with patch.object(o.cliente,'pedir',return_value=None):cargar_lvf(o)
        self.assertFalse(o.tabla)
        o=self.official();o.edicion='lvf:a1:2025/2026'
        self.assertFalse(o._vigente())

    def test_documento_invalido_no_se_disfraza_de_fallo_de_red(self):
        o=self.official()
        with patch.object(o.cliente,'pedir',return_value='<html>old season</html>'):cargar_lvf(o)
        self.assertFalse(o.tabla)
        self.assertEqual(o.status['state'],'rejected_schema_or_season')

    def test_nueva_edicion_lnv_no_reutiliza_anterior_si_falla_la_descarga(self):
        o=self.official('lnv')
        with patch.object(o.cliente,'pedir',side_effect=['https://lnv-web.dataproject.com/Statistics_AllPlayers.aspx?ID=999',None]):
            cargar_lnv(o)
        self.assertFalse(o.tabla)

    def test_snapshot_sobrevive_reinicio_sin_extender_retencion(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(U,'DATA_DIR',tmp),patch.object(U,'usa_upstash',return_value=False):
            o=self.official();o.guardar_contexto()
            restored=Oficial('lvf')
            self.assertEqual(restored.historial,o.historial)
            self.assertEqual(restored.last_verified,o.last_verified)
            with patch('voley_oficial.time.time',return_value=o.last_verified+49*3600):
                self.assertFalse(Oficial('lvf').tabla)

    def test_fallo_detalle_no_borra_resultados(self):
        o=self.official('lnv')
        with patch.object(o.cliente,'pedir',return_value=None):completar_lnv(o,'123','1')
        self.assertEqual(o.historial,[{'id':'verified'}])


class FollowupTests(unittest.TestCase):
    def tracker(self):
        with patch.object(U,'cargar_json',return_value={}):return R.Resultados(Mock(),clock=lambda:2_000_000_000)

    def item(self,age=86400,decision='alert',state='resolved'):
        ev=evento();ev['startTimestamp']=2_000_000_000-age
        return {'event':ev,'sid':'old','decision':decision,'state':state,'outcome':'result' if state=='resolved' else None,
                'next':0,'attempts':0,'favoured':'Local','label':{'won':True,'dominance':True}}

    def test_libera_resueltos_y_conserva_metricas_sin_doble_conteo(self):
        r=self.tracker();r.data['tracked']['one']=self.item(age=4*86400)
        r.mantener();r.mantener()
        self.assertEqual(r.estado()['tracked_events'],0)
        self.assertEqual(r.estado()['sports']['Soccer']['wins'],1)
        self.assertEqual(r.estado()['sports']['Soccer']['win_rate'],1)

    def test_ventana_correcciones_y_caducidad_90dias(self):
        r=self.tracker();r.data['tracked']['one']=self.item(age=86400)
        r.mantener();self.assertEqual(r.estado()['tracked_events'],1)
        r.data['tracked']['one']['event']['startTimestamp']-=4*86400
        r.mantener();self.assertEqual(r.estado()['summary_days'],1)
        r.clock=lambda:2_000_000_000+91*86400
        r.mantener();self.assertEqual(r.estado()['summary_days'],0)

    def test_alerta_no_se_sustituye_por_descarte(self):
        r=self.tracker();item=self.item(age=-3600,state='pending');r.data['tracked']['one']=item
        r.seguir(item['event'],'one','new','discard',{'favorito':'Visitante'})
        self.assertEqual(item['decision'],'alert');self.assertEqual(item['favoured'],'Local')

    def test_reserva_y_prioridad_alertas_con_migracion_llena(self):
        r=self.tracker();item=self.item(age=-3600,decision='discard',state='pending')
        r.data['tracked']={str(i):copy.deepcopy(item) for i in range(1000)}
        r.seguir(item['event'],'alert','sid','alert',{'favorito':'Local'})
        self.assertEqual(len(r.data['tracked']),1000)
        self.assertEqual(r.data['tracked']['alert']['decision'],'alert')
        self.assertEqual(r.estado()['capacity']['non_alerts_replaced'],1)
        r.seguir(item['event'],'discard','sid','discard')
        self.assertNotIn('discard',r.data['tracked'])

    def test_recoge_cada_id_y_mantiene_consulta_diaria_agrupada(self):
        r=self.tracker()
        r.data['tracked']={k:self.item(state='pending') for k in ('a','b')}
        for k,t in r.data['tracked'].items():t['event'].update(id=k,fuente='sportsapi_app')
        per_event=Mock();per_event.resultados_evaluacion.return_value=[]
        per_day=Mock();per_day.resultados_evaluacion.return_value=[]
        r.recoger({'sportsapi_app':per_event,'espn':per_day})
        self.assertEqual(per_event.resultados_evaluacion.call_count,2)
        self.assertEqual(per_day.resultados_evaluacion.call_count,1)

    def test_porcentaje_desconocido_sin_alertas_resueltas(self):
        r=self.tracker();r.data['tracked']['a']=self.item(state='pending')
        self.assertIsNone(r.estado()['sports']['Soccer']['win_rate'])

    def test_conflicto_no_desaparece_por_ausencia_de_una_fuente(self):
        r=self.tracker();ev=evento();r.data['tracked']['a']=self.item(state='pending')
        names=[U.firma_equipo(ev[l]['nombre']) for l in ('local','visita')]
        base={'sport':'Soccer','source':'espn','provider_id':ev['id'],'participants':names,
              'status':'normal','winner':names[0],'score':[4,0]}
        other=dict(base,source='other',score=[3,0])
        with patch.object(R,'compatible',return_value=True):
            r.incorporar([base,other]);r.incorporar([base])
        self.assertEqual(r.data['tracked']['a']['state'],'conflict')

    def test_informe_offline_no_cuenta_favorito_ausente_como_derrota(self):
        decision={'event_key':'a','decision':'alert','sport':'Soccer','pre_match':True,'observed_at_utc':100,
                  'kickoff_utc':200,'participants':[{'nombre':'A'},{'nombre':'B'}],'favoured_participant_id':None,
                  'evidence':{'result':{}}}
        report=E.evaluar([decision],{'a':{'status':'normal','winner':'a','score':[4,0]}})['sports']['Soccer']
        self.assertEqual(report['live_ungraded'],1)
        self.assertIsNone(report['live_win_wilson_95'])


    def test_informe_conserva_primera_alerta_y_descarta_postpartido(self):
        d={'event_key':'a','decision':'alert','sport':'Soccer','pre_match':True,'observed_at_utc':100,
           'kickoff_utc':200,'participants':[{'nombre':'A'},{'nombre':'B'}],'favoured_participant_id':'Local',
           'evidence':{'result':{}}}
        outcomes={'a':{'status':'normal','winner':'a','score':[4,0]}}
        rows=[dict(d,observed_at_utc=150,decision='discard'),d,dict(d,observed_at_utc=250)]
        report=E.evaluar(rows,outcomes)['sports']['Soccer']
        self.assertEqual(report['live_alerts'],1)
        self.assertEqual(report['live_wins'],1)


    def test_cota_por_id_no_aplica_backoff_a_partidos_no_consultados(self):
        r=self.tracker()
        r.data['tracked']={str(i):self.item(state='pending') for i in range(10)}
        for k,t in r.data['tracked'].items():t['event'].update(id=k,fuente='sportsapi_app')
        per_event=Mock();per_event.resultados_evaluacion.return_value=[]
        r.recoger({'sportsapi_app':per_event})
        deferred=[t for t in r.data['tracked'].values() if t['attempts']==0]
        self.assertEqual(len(deferred),2)
        self.assertTrue(all(t['next']==r.clock()+900 and not t.get('checked') for t in deferred))


if __name__=='__main__':unittest.main()
