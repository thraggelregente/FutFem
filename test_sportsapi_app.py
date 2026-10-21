"""Contrato v2 y cuota compartida: sin credenciales, red ni Telegram."""
import test_radar
import copy
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock
import utilidades as U
import fuente_sportsapi_app as S
import main as B
import mapa_fuentes as MAP
import motor_tenis as T
from presupuesto_mensual import DiarioMensual


def raw(sport='Volleyball',finished=False):
    now=time.time()
    return {'id':101,'sport':S.DEPORTES[sport],
        'startTime':datetime.fromtimestamp(now+3600 if not finished else now-86400,timezone.utc).isoformat(),
        'league':{'id':1,'name':'League Women','category':'Italy'},'season':{'id':2,'year':'2026'},
        'home':{'id':10,'name':'A'},'away':{'id':20,'name':'B'},
        'homeScore':{'current':3 if finished else None,'normalTime':None,'periods':{}},
        'awayScore':{'current':0 if finished else None,'normalTime':None,'periods':{}},
        'status':{'type':'finished' if finished else 'notstarted','phase':'finished' if finished else 'notstarted',
                  'finish':'regular' if finished else None},'winner':'home' if finished else None}


class ContractTests(unittest.TestCase):
    def test_calendario_para_siete_deportes_con_misma_cuota(self):
        for sport in S.DEPORTES:
            event=S.normalizar(raw(sport),sport)
            self.assertEqual(event['fuente'],'sportsapi_app')
            self.assertTrue(event['historial_aislado'])
            self.assertEqual(event['local']['id'],'sapp:10')
            self.assertTrue(event['femenino_seguro'])

    def test_no_deduce_genero_por_nombres_o_catalogo_masculino(self):
        r=raw();r['league']['name']='Serie A';r['home']['name']='Some Women'
        self.assertIsNone(S.normalizar(r,'Volleyball'))
        r['league']['name']='Men Women';self.assertIsNone(S.normalizar(r,'Volleyball'))

    def test_no_confunde_simulados_dobles_y_horarios(self):
        for label in ('Women Doubles','Women SRL','Women Virtual'):
            r=raw('Tennis');r['league']['name']=label
            self.assertIsNone(S.normalizar(r,'Tennis'))
        r=raw();r['startTime']='2026-10-21';self.assertIsNone(S.normalizar(r,'Volleyball'))

    def test_no_transforma_live_aplazados_o_marcador_en_pre(self):
        for field,value in (('type','inprogress'),('type','postponed'),('phase','delayed')):
            r=raw();r['status'][field]=value
            self.assertIsNone(S.normalizar(r,'Volleyball'))
        r=raw();r['homeScore']['current']=1;self.assertIsNone(S.normalizar(r,'Volleyball'))

    def test_historial_terminado_y_coherente(self):
        r=raw(finished=True)
        self.assertEqual(S.normalizar(r,'Volleyball')['puntos_local'],3)
        for finish in ('overtime','penalties','walkover','retired','goldenSet'):
            b=copy.deepcopy(r);b['status']['finish']=finish;self.assertIsNone(S.normalizar(b,'Volleyball'))
        r['winner']='away';self.assertIsNone(S.normalizar(r,'Volleyball'))

    def test_no_toma_puntos_de_rally_como_sets(self):
        r=raw(finished=True);r['homeScore']['current']=75;r['awayScore']['current']=60
        self.assertIsNone(S.normalizar(r,'Volleyball'))

    def test_historial_se_aisla_por_liga_y_temporada(self):
        event=S.normalizar(raw(),'Volleyball');valid=raw(finished=True)
        other=copy.deepcopy(valid);other['season']['id']=5;other['id']=102
        with patch.object(S,'_get',return_value={'data':[valid,other],'meta':{'type':'recent'}}):
            self.assertEqual(len(S.historial_equipo(event,'local')),1)

    def test_tabla_exige_edicion_y_ambos_participantes(self):
        event=S.normalizar(raw(),'Volleyball')
        rows=[{'position':i,'team':{'id':pid,'name':name},'played':6,'wins':w,'draws':0,'losses':6-w}
              for i,pid,name,w in ((1,10,'A',6),(2,20,'B',0))]
        data={'data':[{'overall':True,'rows':rows}],'meta':{'season':2,'type':'total'}}
        with patch.object(S,'_get',return_value=data):self.assertEqual(S.tabla_partido(event)[1],2)
        data['meta']['season']=3
        with patch.object(S,'_get',return_value=data):self.assertEqual(S.tabla_partido(event),(None,0))
        data['meta']['season']=2;rows[1]['team']['name']='Different'
        with patch.object(S,'_get',return_value=data):self.assertEqual(S.tabla_partido(event),(None,0))

    def test_tablas_ambiguas_o_inconsistentes_no_se_eligen(self):
        event=S.normalizar(raw(),'Volleyball')
        rows=[{'position':i,'team':{'id':pid,'name':name},'played':6,'wins':w,'draws':0,'losses':6-w}
              for i,pid,name,w in ((1,10,'A',6),(2,20,'B',0))]
        data={'data':[{'rows':rows},{'rows':rows}],'meta':{'season':2,'type':'total'}}
        with patch.object(S,'_get',return_value=data):self.assertEqual(S.tabla_partido(event),(None,0))

    def test_h2h_agregado_no_se_convierte_en_partidos_fechados(self):
        # El adaptador sólo ofrece cruces individuales a través de historial validado.
        self.assertFalse(hasattr(S,'h2h_partido'))

    def test_main_usa_el_historial_del_nuevo_proveedor_sin_buscar_por_nombre(self):
        event=S.normalizar(raw(),'Volleyball')
        rows=[{'id':'historial'}]
        with patch.object(B,'fuente_sportsapi_app',SimpleNamespace(historial_equipo=lambda ev,lado:rows)),patch.object(B,'_contextos_oficiales',return_value=[]):
            self.assertEqual(B._historial_equipo(event,'local'),rows)
            self.assertTrue(B._tiene_historial_propio(event))

    def test_capacidades_reflejan_siete_deportes_no_los_veinte_anunciados(self):
        module=SimpleNamespace(disponible=lambda:True,DEPORTES_ACTIVOS=S.DEPORTES_ACTIVOS)
        data=MAP.construir({'sportsapi_app':module},False)['sports']
        self.assertEqual(sum('sportsapi_app' in r['configured_sources'] for r in data.values()),7)
        self.assertNotIn('sportsapi_app',data['Cricket']['configured_sources'])

    def test_eliminatoria_no_recibe_tabla_de_fase_regular(self):
        event=S.normalizar(raw(),'Volleyball');event['round_name']='Semifinal'
        with patch.object(S,'_get') as get:
            self.assertEqual(S.tabla_partido(event),(None,0));get.assert_not_called()

    def test_historial_corto_no_se_presenta_como_dos_anios_completos(self):
        event={'local':{'nombre':'A','ranking':10},'visita':{'nombre':'B','ranking':200}}
        profiles={lado:{'fuente':'SportsAPI.app historial','muestras_2anios':4,'ventana_historial_dias':90,
                        'partidos':[],'recientes':[]} for lado in ('Local','Visitante')}
        result=T.evaluar(event,profiles)
        self.assertIn('90 días',next(e for e in result['evidencia'] if e.startswith('Historial disponible:')))

    def test_perfil_tenis_no_inventa_ranking_o_completitud(self):
        event=S.normalizar(raw('Tennis'),'Tennis');r=raw('Tennis',True)
        r['league']['name']='WTA'
        r['homeScore'].update(current=2,periods={'period1':6,'period2':6})
        r['awayScore'].update(current=0,periods={'period1':1,'period2':2})
        with patch.object(S,'_get',return_value={'data':[r],'meta':{'type':'recent'}}):
            p=S.perfil_tenis(event,'local')
            self.assertEqual(p['ventana_historial_dias'],90)
            self.assertFalse(p['cobertura_completa_2anios'])
            self.assertIsNone(p['partidos'][0]['ranking_rival'])
            self.assertEqual(p['partidos'][0]['juegos_favor'],12)


class QuotaTests(unittest.TestCase):
    def test_preserva_contador_diario_al_agregar_tope_mensual(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(U,'DATA_DIR',tmp),patch.object(U,'usa_upstash',return_value=False):
            U.guardar_json('presupuesto_migration.json',{'fecha':U.PresupuestoDiario._hoy(),'usadas':123})
            p=DiarioMensual('migration',2000,14000,'2026-11-01')
            self.assertEqual(p.usadas,123)
            self.assertEqual(p.usadas_mes,123)
            self.assertFalse(p.completo)

    def test_limite_mensual_se_activa_noviembre_y_persiste(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(U,'DATA_DIR',tmp),patch.object(U,'usa_upstash',return_value=False),patch.object(DiarioMensual,'_hoy',return_value='2026-11-01'):
            p=DiarioMensual('newmonth',2000,14000,'2026-11-01')
            p.usadas_mes=13999;p.registrar()
            self.assertEqual(p.restantes(),0)
            self.assertEqual(DiarioMensual('newmonth',2000,14000,'2026-11-01').restantes(),0)
            with patch.object(DiarioMensual,'_hoy',return_value='2026-12-01'):
                self.assertEqual(p.restantes(),2000)
                self.assertTrue(p.completo)

    def test_en_octubre_no_aplica_un_limite_que_aun_no_rige(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(U,'DATA_DIR',tmp),patch.object(U,'usa_upstash',return_value=False),patch.object(DiarioMensual,'_hoy',return_value='2026-10-31'):
            p=DiarioMensual('october',2000,14000,'2026-11-01');p.usadas_mes=14000
            self.assertEqual(p.restantes(),2000)

    def test_cien_requests_compartidos_no_cien_por_deporte(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(U,'DATA_DIR',tmp),patch.object(U,'usa_upstash',return_value=False):
            quota=U.PresupuestoDiario('test_sapp',100,reserva=0)
            cache=Mock();cache.get.return_value=(False,None)
            response=SimpleNamespace(status_code=200,headers={'RateLimit-Remaining':'0'},content=b'{}',json=lambda:{'data':[]})
            with patch.object(S,'API_KEY','test'),patch.object(S,'_disabled',False),patch.object(S,'_pausa',0),patch.object(S,'_state',{}),patch.object(S,'presupuesto',quota),patch.object(S,'_cache',cache),patch.object(S._ritmo,'esperar'),patch.object(S.P.actual,'permitido',return_value=True),patch.object(S.requests,'get',return_value=response) as get:
                for i in range(40):S._get('/v2/fixtures',{'page':i},calendar=True)
                self.assertIsNone(S._get('/v2/fixtures',{'page':41},calendar=True))
                for i in range(60):S._get('/v2/teams/'+str(i)+'/fixtures')
                self.assertIsNone(S._get('/v2/teams/999/fixtures'))
                self.assertEqual(get.call_count,100)
                self.assertEqual(quota.usadas,100)
                # El saldo por minuto nunca sobrescribe el diario.
                self.assertIsNone(quota.saldo_proveedor)

    def test_cache_hits_no_consumen_solicitudes(self):
        cache=Mock();cache.get.return_value=(True,{'data':[]})
        with patch.object(S,'API_KEY','test'),patch.object(S,'_disabled',False),patch.object(S,'_cache',cache),patch.object(S.requests,'get') as get:
            self.assertEqual(S._get('/v2/sports'),{'data':[]});get.assert_not_called()

    def test_sin_key_no_llama_a_red(self):
        with patch.object(S,'API_KEY',''),patch.object(S.requests,'get') as get:
            self.assertIsNone(S._get('/v2/sports'));get.assert_not_called()


if __name__=='__main__':unittest.main()
