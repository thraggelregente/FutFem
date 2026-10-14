"""Identidad, temporalidad, presupuesto y contratos reales del pack de contexto."""
import test_radar
import unittest
from unittest.mock import patch,Mock
import time
from datetime import datetime,timezone,timedelta
import xml.etree.ElementTree as E
import fuente_tennis_api as T
import fuente_fivb as F
import motor_tenis as M
from voley_oficial import Oficial,parse_html,detalle_lvf,detalle_lnv,_puntos_validos,temporada_actual
import resultados_evaluacion as R
import utilidades as U


def player():return {'nombre':'Anna Player','tennis_api_id':1}

def match():
    return {'id':10,'date':datetime.fromtimestamp(time.time()-86400,timezone.utc).isoformat(),
            'player1':{'id':2,'name':'Betty Player'},'player2':{'id':1,'name':'Anna Player'},
            'result_type':'completed','result':'6-1 6-0','tournamentId':1,'roundId':2,'match_winner':2,
            'tournament':{'courtId':2,'rankId':1}}


class TennisContextTests(unittest.TestCase):
    def test_history_orients_losing_player(self):
        p=T.normalizar_historial(match(),1)
        self.assertFalse(p['gano']);self.assertEqual(p['juegos_favor'],1);self.assertEqual(p['juegos_contra'],12)
        self.assertIsNone(p['ranking_rival'])

    def test_future_retirement_foreign_identity_rejected(self):
        raw=match()
        self.assertIsNone(T.normalizar_historial(dict(raw,date=datetime.fromtimestamp(time.time()+86400,timezone.utc).isoformat()),1))
        self.assertIsNone(T.normalizar_historial(dict(raw,result_type='retired'),1))
        self.assertIsNone(T.normalizar_historial(raw,99))

    def test_incomplete_and_reversed_score_rejected(self):
        self.assertIsNone(T.normalizar_historial(dict(match(),result='6-1 1-0'),1))
        self.assertIsNone(T.normalizar_historial(dict(match(),result='1-6 0-6'),1))

    def test_profile_identity_and_fresh_ranking(self):
        payload={'data':{'id':1,'name':'Anna Player','currentRank':500,'rankingDate':datetime.now(timezone.utc).date().isoformat(),'bestRank':{'rank':100}},'fetched_at':time.time()}
        with patch.object(T,'_get',return_value=payload):
            p=T.perfil_basico(player());self.assertEqual(p['ranking'],500)
            self.assertIsNone(T.perfil_basico(dict(player(),nombre='Someone Else')))
        payload['data']['rankingDate']='2025-01-01'
        with patch.object(T,'_get',return_value=payload):self.assertIsNone(T.perfil_basico(player())['ranking'])

    def test_same_date_conflict_preserves_official_rank(self):
        fecha=datetime.now(timezone.utc).date().isoformat()
        j=dict(player(),ranking=10,ranking_fecha=fecha)
        payload={'data':{'id':1,'name':j['nombre'],'currentRank':11,'rankingDate':fecha},'fetched_at':time.time()}
        with patch.object(T,'_get',return_value=payload):T.perfil_basico(j)
        self.assertEqual(j['ranking'],10);self.assertTrue(j['ranking_conflicto'])

    def test_complement_never_adds_history_as_independent_sample(self):
        official={'fuente':'WTA historial oficial','muestras_2anios':3,'partidos':[1]}
        extra={'fuente':'Tennis API historial WTA/ITF','muestras_2anios':20,'partidos':[2]}
        merged=T.complementar(official,extra)
        self.assertEqual(merged['partidos'],[1]);self.assertEqual(merged['complemento_tennis_api'],extra)

    def test_itf_experience_prevents_false_novice(self):
        p={'experiencia_carrera_wta':0,'muestras_2anios':0,'cobertura_completa_2anios':True}
        self.assertTrue(M._novata_documentada(p))
        self.assertFalse(M._novata_documentada(dict(p,complemento_tennis_api={'muestras_2anios':20})))

    def test_context_reserve_and_cycle_limit(self):
        with patch.object(T._cache,'get',return_value=(False,None)),patch.object(T,'disponible',return_value=True), \
             patch.object(T,'_context_calls',6),patch.object(T.presupuesto,'puede_gastar',return_value=True), \
             patch.object(T.presupuesto,'restantes',return_value=40),patch.object(U,'get_json') as request:
            self.assertIsNone(T._get('/profile',{},100,profile=True,context=True));request.assert_not_called()
        with patch.object(T._cache,'get',return_value=(False,None)),patch.object(T,'disponible',return_value=True), \
             patch.object(T,'_context_calls',0),patch.object(T.presupuesto,'puede_gastar',return_value=True), \
             patch.object(T.presupuesto,'restantes',return_value=8),patch.object(U,'get_json') as request:
            self.assertIsNone(T._get('/profile',{},100,profile=True,context=True));request.assert_not_called()

    def test_profile_allowlist_strips_odds_before_cache(self):
        payload={'data':{'id':1,'name':'Anna Player','odd1':1.01,'prediction':{},'currentRank':2,'rankingDate':'2026-10-12'}}
        with patch.object(T._cache,'get',return_value=(False,None)),patch.object(T,'disponible',return_value=True), \
             patch.object(T,'_pause',0),patch.object(T.presupuesto,'puede_gastar',return_value=True), \
             patch.object(T.presupuesto,'registrar'),patch.object(T._ritmo,'esperar'),patch.object(U,'get_json',return_value=payload), \
             patch.object(T._cache,'set') as cache:
            r=T._get('/profile',{},100,profile=True)
        self.assertNotIn('odd1',r['data']);self.assertNotIn('prediction',r['data'])
        self.assertEqual(cache.call_args.args[1],r)


class VolleyballTests(unittest.TestCase):
    def test_set_points_validate_winner_and_deciding_set(self):
        self.assertTrue(_puntos_validos([[25,15],[25,17],[25,23]],[3,0]))
        self.assertFalse(_puntos_validos([[25,15],[25,17]],[3,0]))
        self.assertFalse(_puntos_validos([[25,15],[25,17],[23,25]],[3,0]))
        self.assertFalse(_puntos_validos([[25,24],[25,17],[25,23]],[3,0]))

    def test_nested_tables_keep_outer_standings_cells(self):
        p=parse_html('<table><tr><td><table><tr><td>Team</td></tr></table></td><td>9</td></tr></table>')
        outer=p.tables[-1]['rows'][0]
        self.assertEqual([c['text'] for c in outer],['Team','9'])

    def test_national_scope_and_exact_alias(self):
        o=Oficial('lvf');o.edicion='lvf:a1:'+temporada_actual()
        o.tabla={U.firma_equipo('Prosecco Doc Imoco Conegliano'):{'nombre':'Prosecco Doc Imoco Conegliano','posicion':1},
                 U.firma_equipo('Numia Vero Volley Milano'):{'nombre':'Numia Vero Volley Milano','posicion':2}}
        ev={'deporte':'Volleyball','fuente':'oddspapi','torneo':'Serie A1 Women (Italy)',
            'local':{'nombre':'Conegliano Women','id':'a'},'visita':{'nombre':'Milano Women','id':'b'}}
        self.assertEqual(o.tabla_para_evento(ev)[1],2)
        self.assertIsNone(o.tabla_para_evento(dict(ev,torneo='CEV Champions League Women'))[0])
        self.assertIsNone(o.tabla_para_evento(dict(ev,torneo='Serie A1 Women U19'))[0])
        self.assertIsNone(o.resolver('Unknown Conegliano City'))

    def test_lvf_stale_season_rejected(self):
        o=Oficial('lvf')
        text='<a class="dropdown-item active" href="/?stagione=2025"><b>2025/2026</b></a>'
        self.assertFalse(o.cargar_lvf(text,datetime(2026,10,14,tzinfo=timezone.utc).timestamp()))

    def test_fivb_table_must_reconcile_current_group(self):
        now=time.time()
        ev={'fivb_pool':'3','fivb_start':datetime.fromtimestamp(now-86400*10,timezone.utc).isoformat(),
            'fivb_end':datetime.fromtimestamp(now+86400*10,timezone.utc).isoformat(),'startTimestamp':now+3600,
            'contexto_competicion':'fivb:1','local':{'id':'fivb:1'},'visita':{'id':'fivb:2'}}
        hist=[{'id':'one','fivb_pool':'3','contexto_competicion':'fivb:1','id_local':'fivb:1','id_visita':'fivb:2','puntos_local':3,'puntos_visita':0}]
        root=E.fromstring('<VolleyballPoolRankings><VolleyballPoolRanking NoTeam="1" NoPool="3" Position="1" MatchesWon="1" MatchesLost="0" SetsWon="3" SetsLost="0"/><VolleyballPoolRanking NoTeam="2" NoPool="3" Position="2" MatchesWon="0" MatchesLost="1" SetsWon="0" SetsLost="3"/></VolleyballPoolRankings>')
        self.assertIsNotNone(F.normalizar_tabla(root,ev,hist,now)[0])
        root[0].set('MatchesWon','2')
        self.assertIsNone(F.normalizar_tabla(root,ev,hist,now)[0])

    def test_national_history_remaps_both_ids(self):
        o=Oficial('lvf');o.edicion='lvf:a1:'+temporada_actual()
        a,b=U.firma_equipo('Conegliano'),U.firma_equipo('Milano')
        o.tabla={a:{'nombre':'Conegliano'},b:{'nombre':'Milano'}}
        o.historial=[o._historico(a,b,[3,0],time.time()-86400,'1',[[25,15],[25,17],[25,23]])]
        ev={'deporte':'Volleyball','fuente':'oddspapi','torneo':'Serie A1 Women (Italy)','local':{'id':'a','nombre':'Conegliano'},'visita':{'id':'b','nombre':'Milano'}}
        r=o.historial_para_evento(ev,'local')[0]
        self.assertEqual((r['id_local'],r['id_visita']),('a','b'))

    def test_national_outcome_link_requires_exact_time(self):
        o=Oficial('lvf');o.edicion='lvf:a1:'+temporada_actual()
        a,b=U.firma_equipo('Conegliano'),U.firma_equipo('Milano');ts=int(time.time())-86400
        o.tabla={a:{'nombre':'Conegliano'},b:{'nombre':'Milano'}}
        o.historial=[o._historico(a,b,[3,0],ts,'1')]
        ev={'id':'fixture','deporte':'Volleyball','fuente':'oddspapi','torneo':'Serie A1 Women (Italy)','startTimestamp':ts,
            'local':{'id':'a','nombre':'Conegliano'},'visita':{'id':'b','nombre':'Milano'}}
        rows=o.resultados_para_evento(ev)
        self.assertEqual(len(rows),1);self.assertTrue(R.compatible(ev,rows[0]))
        self.assertEqual(o.resultados_para_evento(dict(ev,startTimestamp=ts+3600)),[])


if __name__=='__main__':unittest.main()
