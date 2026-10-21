"""Selección de mercados, ausencia de datos, formatos y replay histórico."""
import test_radar
import copy
import time
import unittest
from datetime import datetime, timezone

import analisis_deportivo as A
import motor_tenis as T
import motor_tenis_legacy as L
import motor_voley as V
import mensajes as S
import evaluacion_motor as E
import cobertura_radar as C

NOW=1792555200


def fixture(sport='Volleyball'):
    return {'deporte':sport,'torneo':'Liga femenina', 'local':{'id':'a','nombre':'A'},
            'visita':{'id':'b','nombre':'B'},'startTimestamp':NOW+3600}


def sample(pid, a, b, n=8):
    return [{'fecha':datetime.fromtimestamp(NOW-(i+1)*86400,timezone.utc).isoformat(),
             'id_local':pid,'id_visita':str(i)+'rival','puntos_local':a,'puntos_visita':b} for i in range(n)]


def result():
    return {'hay_mismatch':True,'favorito':'Local','calidad_datos':'Suficiente',
            'familias_senales':['historial','tabla'],
            'signals':[{'side':'Local','family':'historial','effective_points':2}]}


class RecomendacionesTests(unittest.TestCase):
    def test_contadores_solo_cuentan_ultima_decision_por_partido(self):
        c=C.Cobertura();c.evento('a',fixture('Tennis'))
        for _ in range(2):c.decision('a','alert','threshold',{'analisis_deportivo':{'selecciones':[]}})
        self.assertEqual(c.resumen()['sports']['Tennis']['recommendations'],
                         {'evaluated':1,'with_market':0,'without_market':1})

    def test_voley_recomienda_ganador_y_linea_con_muestras_fuertes(self):
        r=A.equipos(fixture(),result(),sample('a',3,0),sample('b',0,3),NOW)
        self.assertEqual(len(r['selecciones']),2)
        self.assertIn('−1,5',r['selecciones'][1]['mercado'])
        self.assertIn('8/8',r['selecciones'][1]['motivo'])
        self.assertNotIn('probabilidad',r['selecciones'][1]['motivo'])

    def test_no_usa_3_2_para_hacer_handicap(self):
        r=A.equipos(fixture(),result(),sample('a',3,2),sample('b',2,3),NOW)
        self.assertEqual(len(r['selecciones']),1)

    def test_no_selecciona_con_historial_corto_o_solo_tabla(self):
        for res, n in ((result(),3),(dict(result(),signals=[]),8),
                       (dict(result(),calidad_datos='Limitada'),8),
                       (dict(result(),familias_senales=['historial']),8)):
            self.assertEqual(A.equipos(fixture(),res,sample('a',3,0,n),sample('b',0,3,n),NOW)['selecciones'],[])

    def test_sets_y_puntos_incompletos_no_se_confunden(self):
        rows=sample('a',25,10)+sample('a',2,1)+sample('a',3,3)
        self.assertEqual(V.historial_sets(rows),[])
        self.assertEqual(A.equipos(fixture(),result(),rows,sample('b',0,3),NOW)['selecciones'],[])

    def test_duplicados_invertidos_no_inflan_muestra_y_conflictos_rechazan(self):
        rows=sample('a',3,0,4)
        reverse=[dict(p,id_local=p['id_visita'],id_visita='a',puntos_local=0,puntos_visita=3) for p in rows]
        self.assertEqual(len(A._muestra(rows+reverse,'a',NOW,'Volleyball')),4)
        self.assertEqual(A._muestra(rows+[dict(rows[0],puntos_local=0,puntos_visita=3)],'a',NOW,'Volleyball'),[])

    def test_resultados_futuros_y_walkover_no_cuentan(self):
        rows=sample('a',3,0)
        self.assertEqual(V.historial_sets([dict(p,estado_resultado='walkover') for p in rows]),[])
        future=dict(rows[0],fecha=datetime.fromtimestamp(NOW+1,timezone.utc).isoformat())
        self.assertEqual(A._muestra([future],'a',NOW,'Volleyball'),[])

    def test_deportes_con_reglas_no_verificadas_no_proponen_ganador(self):
        for sport in ('Soccer','Rugby','Ice Hockey','Softball','Lacrosse','Field Hockey'):
            self.assertEqual(A.equipos(fixture(sport),result(),sample('a',4,0),sample('b',0,4),NOW)['selecciones'],[])

    def test_basquet_y_handball_sin_handicap_inventado(self):
        for sport in ('Basketball','Handball'):
            r=A.equipos(fixture(sport),result(),sample('a',80,50),sample('b',50,80),NOW)
            self.assertEqual([s['mercado'] for s in r['selecciones']],['Ganador del partido'])

    def test_ejemplo_fernandez_es_candidato_no_apuesta(self):
        ev=fixture('Tennis')
        ev['local'].update(nombre='Leylah Annie Fernandez',ranking=30,ranking_fuente='Tennis API; ranking fechado',ranking_fecha='2026-10-19')
        ev['visita'].update(nombre='Aliaksandra Sasnovich',ranking=122,ranking_fuente='WTA oficial',ranking_fecha='2026-10-19')
        profiles={'Local':{'muestras_2anios':107,'partidos':[],'recientes':[],'fuente':'Tennis API historial WTA/ITF'},
                  'Visitante':{'muestras_2anios':114,'partidos':[],'recientes':[],'fuente':'WTA historial oficial'}}
        r=T.evaluar(ev,profiles,NOW)
        self.assertIn('CANDIDATO',r['tipo'])
        self.assertEqual(r['analisis_deportivo']['selecciones'],[])
        text=S.alerta('Tennis','Ningbo','Leylah Annie Fernandez','Aliaksandra Sasnovich','21/10 03:30 hs (ARG)',
                      r['evidencia'],'Leylah Annie Fernandez','Magnitud: moderada; calidad: Limitada',
                      ['tennis_api','Tennis API historial WTA/ITF','WTA oficial','Tennis API; ranking fechado'],r['tipo'],r['analisis_deportivo'])
        self.assertIn('Sin apuesta recomendada',text)
        self.assertIn('Cobertura y límites',text)
        self.assertIn('puesto #30',text)
        self.assertIn('107 partidos',text)
        self.assertIn('Fuentes: Tennis API · WTA',text)
        self.assertNotIn('Pendientes de evaluación',text)

    def test_h2h_no_duplica_dos_perspectivas_y_fecha_semanal_es_conservadora(self):
        p={'ts':NOW-10*86400,'gano':True,'rival':'B','torneo':1,'round':1,'fecha_precision':'exact'}
        a={'partidos':[p]};b={'partidos':[dict(p,rival='A',gano=False,ts=p['ts']-86400)]}
        h,c=T._cruces(a,b,'A','B',NOW)
        self.assertEqual(h['favor'],1)
        p=dict(p,ts=NOW-2*86400,fecha_precision='semana del torneo')
        self.assertEqual(T._recientes_verificados({'partidos':[p]},NOW),[])

    def test_no_recomienda_si_solo_forma_superficie_solapadas(self):
        r={'tipo':'ASIMETRÍA TENIS FEMENINO','favorito':'Local'}
        self.assertEqual(A.tenis(r,{'brecha':.5},{'brecha':.5},{'favor':0,'contra':0},{'favor':0,'contra':0},[])['selecciones'],[])
        self.assertEqual(len(A.tenis(r,{'brecha':.5},None,{'favor':2,'contra':0},{'favor':0,'contra':0},[])['selecciones']),1)

    def test_replay_legacy_conserva_resultado_original(self):
        ev=fixture('Tennis');ev['local']['ranking']=10;ev['visita']['ranking']=200
        r=L.evaluar(ev,{},NOW)
        snap={'sport':'Tennis','revision_motor':'tennis-volley-context-v1', 'pre_match':True,
              'observed_at_utc':NOW,'kickoff_utc':NOW+3600,
              'evidence':{'event':ev,'inputs':{'perfiles':{},'evaluation_at_utc':NOW}}}
        self.assertEqual(E.replay(snap),r)

    def test_dobles_y_simulados_no_usan_motor_individual(self):
        for tipo in ('Women Doubles','Women SRL'):
            ev=fixture('Tennis');ev['torneo']=tipo
            self.assertFalse(T.evaluar(ev,{},NOW)['alertar'])

    def test_html_escapa_seleccion_y_preserva_todas_las_evidencias(self):
        text=S.alerta('Volleyball','Liga','A','B','Hoy',['Evidencia <test>'],'A','Evaluación',[], 'ASIMETRÍA',
            {'selecciones':[{'mercado':'Ganador','seleccion':'A <B>','motivo':'Motivo & evidencia'}]})
        self.assertIn('A &lt;B&gt;',text)
        self.assertIn('Evidencia &lt;test&gt;',text)
        self.assertIn('Motivo &amp; evidencia',text)


if __name__=='__main__':unittest.main()
