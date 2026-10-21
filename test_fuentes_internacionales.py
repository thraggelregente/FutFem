"""Regresiones de contratos oficiales, aprovechamiento y reparto entre deportes."""
import test_radar
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import auditoria_decisiones as A
import cobertura_radar as C
import fuente_cev as V
import fuente_tauron as T
import planificador_datos as P
import utilidades as U
import voley_oficial as O
import main as B

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc).timestamp()


def poland_fixture():
    title = '<title class="notranslate">{} - Sezon 2026/2027 - TAURON Liga Kobiet</title>'
    rows, games = [], []
    for i in range(1, 7):
        winner = i % 2 == 1
        values = [i, f'<a href="/teams/id/{i}.html">Club {i}</a>', 3 if winner else 0,
                  1, int(winner), int(not winner), 3 if winner else 0, 0 if winner else 3, 75, 45,
                  '-', '-', 1, 0, 0, 0, 0, 0]
        rows.append('<tr data-teamname="Club" class="trodd">'+''.join('<td>'+str(v)+'</td>' for v in values)+'</tr>')
    def match(mid, a, b, ts, scores):
        date = datetime.fromtimestamp(ts, ZoneInfo('Europe/Warsaw')).strftime('%d.%m.%Y, %H:%M')
        return (f'<section class="filterable-content-RS" data-game-id="{mid}" data-team="{a},{b}">'
                f'<div class="game-date">{date}</div><div class="game-team left">Club {a}</div>'
                f'<span data-synced-games-content="setsTeamA">{scores[0]}</span>'
                f'<span data-synced-games-content="setsTeamB">{scores[1]}</span>'
                f'<div class="game-team right">Club {b}</div></section>')
    for i in (1, 3, 5):
        games.append(match(i, i, i+1, NOW-86400, [3, 0]))
    games.append(match(10, 1, 3, NOW+3600, ['···', '···']))
    return title.format('Tabela')+'<table id="rs-standings-table-1-1">'+''.join(rows)+'</table>', title.format('Mecze')+''.join(games)


class PolandTests(unittest.TestCase):
    def test_current_women_season_reconciled_with_results_and_timezone(self):
        o=T.Tauron();table,games=poland_fixture()
        self.assertTrue(o.cargar(table,games,NOW))
        self.assertEqual((len(o.tabla),len(o.historial),len(o.eventos)),(6,3,1))
        self.assertEqual(o.eventos[0]['startTimestamp'],NOW+3600)
        self.assertEqual(o.eventos[0]['season_ref'],'2026/2027')
        self.assertEqual(o.historial_para_evento(o.eventos[0],'local')[0]['puntos_local'],3)

    def test_wrong_gender_stale_season_and_mismatched_scores_rejected(self):
        table,games=poland_fixture()
        for t,g in ((table.replace('Liga Kobiet','Liga'),games),
                    (table.replace('2026/2027','2025/2026'),games),
                    (table,games.replace('>3</span>','>2</span>',1))):
            self.assertFalse(T.Tauron().cargar(t,g,NOW))

    def test_hidden_historical_round_is_not_current_table(self):
        table,games=poland_fixture()
        hidden='<tr data-teamname="Old" class="hidden"><td>broken old row</td></tr>'
        self.assertTrue(T.Tauron().cargar(table.replace('</table>',hidden+'</table>'),games,NOW))

    def test_no_cup_or_juvenile_context_and_remap_both_participants(self):
        o=T.Tauron();self.assertTrue(o.cargar(*poland_fixture(),NOW))
        ev={'deporte':'Volleyball','fuente':'oddspapi','torneo':'TAURON Liga Women (Poland)',
            'local':{'id':'external1','nombre':'Club 1'},'visita':{'id':'external2','nombre':'Club 2'}}
        hist=o.historial_para_evento(ev,'local')
        self.assertEqual((hist[0]['id_local'],hist[0]['id_visita']),('external1','external2'))
        self.assertFalse(o.tabla_para_evento(dict(ev,torneo='Puchar Polski Women'))[0])
        self.assertFalse(o.tabla_para_evento(dict(ev,torneo='TAURON Liga U19 Women'))[0])


def cev_fixture():
    comps={'1':{'Gender':0,'SeasonID':2,'DateFrom':'2026-09-01','DateTo':'2027-06-01'}}
    def raw(mid,ts,done=False):
        return dict(MatchID=mid,CompetitionID=1,CompetitionName='CEV Women 2027',SeasonID=2,
                    ChampionshipID=4,HomeTeamID=1,GuestTeamID=2,HomeTeamName='Club A',GuestTeamName='Club B',
                    MaleNotFemale=False,IsBeach=False,IsSnow=False,
                    MatchDateTime_UTC=datetime.fromtimestamp(ts,timezone.utc).isoformat(),
                    Finalized=done,MatchStatusDescription='Complete' if done else 'Scheduled',
                    WonSetHome=3 if done else 0,WonSetGuest=0)
    target=raw(9,NOW+3600)
    matches=[raw(i,NOW-i*86400,True) for i in range(1,5)]+[target]
    rows=[dict(TeamID=i,StandingPosition=i,MatchesPlayed=4,MatchesWon=4 if i==1 else 0,
               MatchesLost=0 if i==1 else 4,SetsWon=12 if i==1 else 0,SetsLost=0 if i==1 else 12,
               ChampionshipID=4,ChampionshipMethodID=1) for i in (1,2)]
    return comps,V.normalizar(target,comps,NOW),{'matches':matches,'standingGroups':[{'championshipId':4,'rows':rows}]}


class CevTests(unittest.TestCase):
    def test_group_table_reconciles_exact_edition_and_histories(self):
        comps,ev,data=cev_fixture()
        table,n=V.normalizar_tabla(data,ev,comps,NOW)
        self.assertEqual(n,2);self.assertEqual(table['cev:1']['victorias'],4)
        data['standingGroups'][0]['rows'][0]['MatchesWon']=5
        self.assertIsNone(V.normalizar_tabla(data,ev,comps,NOW)[0])

    def test_knockout_wrong_participants_and_season_cannot_supply_table(self):
        comps,ev,data=cev_fixture()
        self.assertIsNone(V.normalizar_tabla(dict(data,standingGroups=[]),ev,comps,NOW)[0])
        self.assertIsNone(V.normalizar_tabla(data,dict(ev,contexto_competicion='cev:1:99'),comps,NOW)[0])
        self.assertIsNone(V.normalizar_tabla(data,dict(ev,local={'id':'cev:99'}),comps,NOW)[0])

    def test_group_request_cap_does_not_bypass_public_budget(self):
        comps,ev,data=cev_fixture()
        with patch.object(V,'ACTIVO',True),patch.object(V,'_competiciones',comps),patch.object(V,'_tablas_ciclo',{}), \
             patch.object(V,'_table_calls',2),patch.object(V._cache,'get',return_value=(False,None)),patch.object(V.cliente,'pedir') as req:
            self.assertIsNone(V.tabla_partido(ev)[0]);req.assert_not_called()


class ContextAndSchedulingTests(unittest.TestCase):
    def test_away_only_h2h_and_reverse_duplicates(self):
        ev={'local':{'id':'a'},'visita':{'id':'b'}}
        p=test_radar.partido()
        reverse=dict(p,id_local='b',id_visita='a',puntos_local=1,puntos_visita=4)
        self.assertEqual(len(U.h2h_desde_fuentes(ev,[],[p],None,None,'b')),1)
        self.assertEqual(len(U.h2h_desde_fuentes(ev,[p],[reverse],None,None,'b')),1)
        self.assertEqual(U.h2h_desde_fuentes(ev,[],[dict(p,id_visita='c')],None,None,'b'),[])

    def test_round_robin_stops_tennis_starving_other_sports(self):
        events=[{'id':str(i),'deporte':'Tennis','startTimestamp':i+1000} for i in range(200)]
        events += [{'id':s,'deporte':s,'startTimestamp':1500} for s in ('Volleyball','Soccer','Handball')]
        result=P.Planificador().ordenar_eventos(events,{},lambda e:e['id'],now=100)
        self.assertEqual({e['deporte'] for e in result[:4]},{'Tennis','Volleyball','Soccer','Handball'})
        self.assertEqual([e['id'] for e in result if e['deporte']=='Tennis'],[str(i) for i in range(200)])

    def test_known_official_context_avoids_identity_budget_and_commercial_lookup(self):
        ev=test_radar.evento('A',deporte='Volleyball');ev['fuente']='oddspapi'
        official=Mock();official.disponible.return_value=True;official.tabla_partido.return_value=({'A':{}},2)
        official.historial_equipo.return_value=[test_radar.partido('A','rA',dias=i+1) for i in range(4)]
        with patch.object(B,'fuente_lvf',official),patch.object(B,'fuente_lnv',None),patch.object(B,'fuente_tauron',None), \
             patch.object(U,'historial_desde_fuentes') as commercial:
            self.assertTrue(B._tiene_historial_propio(ev))
            self.assertEqual(len(B._historial_equipo(ev,'local')),4)
            commercial.assert_not_called()

    def test_isolated_international_does_not_import_domestic_history(self):
        ev=test_radar.evento('A',deporte='Volleyball');ev.update(fuente='cev',historial_aislado=True,torneo='CEV Champions League Women')
        cev=Mock();cev.historial_equipo.return_value=[]
        with patch.object(B,'fuente_cev',cev),patch.object(B,'_contextos_oficiales',return_value=[]), \
             patch.object(U,'historial_desde_fuentes') as commercial:
            self.assertEqual(B._historial_equipo(ev,'local'),[]);commercial.assert_not_called()

    def test_verified_national_aliases_share_identity_but_keep_old_alert_key(self):
        ev=test_radar.evento('A',deporte='Volleyball')
        table={'A':{'nombre':'Official Sponsor A'},'rA':{'nombre':'Official Sponsor Rival'}}
        official=Mock();official.tabla_partido.return_value=(table,2)
        original=B._clave_canonica_evento(ev)
        with patch.object(B,'_contextos_oficiales',return_value=[official]):
            self.assertIn(original,B._claves_equivalentes(ev))
            other=dict(ev,local={'id':'A','nombre':'Different A'},visita={'id':'rA','nombre':'Different Rival'})
            self.assertEqual(B._clave_canonica_evento(ev),B._clave_canonica_evento(other))

    def test_collection_does_not_spend_details_on_unrequested_teams(self):
        o=O.Oficial('lvf');o.edicion='lvf:a1:2026/2027'
        o._lvf_pending=[dict(match_id='1',a='team-a',b='team-b',score=[3,0])]
        with patch.object(o.cache,'get',return_value=(False,None)),patch.object(o.cliente,'pedir',return_value=None) as req:
            O.completar_lvf(o,set());req.assert_not_called()
            O.completar_lvf(o,{'team-a'});self.assertEqual(req.call_count,1)
            self.assertEqual(o.details_cycle,1)

    def test_coverage_separates_context_from_calendar_provider_count(self):
        c=C.Cobertura();ev=test_radar.evento('A',deporte='Volleyball');c.evento('one',ev)
        c.contexto('one',[{'fuente':'lvf'}]*4,[{'fuente':'lvf'}]*4,[],{'a':{'fuente':'lvf'}})
        data=c.resumen()['sports']['Volleyball']['context_evaluations']
        self.assertEqual(data['both_histories_4plus'],1);self.assertEqual(data['sources_used'],['lvf'])

    def test_audit_reserves_capacity_without_deleting_old_records(self):
        with patch.object(U,'cargar_json',return_value={}),patch.object(A,'MAX_RECORDS',10):
            diary=A.Diario()
            for i in range(8):self.assertIsNotNone(diary.guardar('decision',{'event_key':str(i),'evaluated':False}))
            self.assertIsNone(diary.guardar('decision',{'event_key':'extra','evaluated':False}))
            self.assertIsNotNone(diary.guardar('decision',{'event_key':'evaluated','evaluated':True},{'history':[1]}))
            self.assertEqual(len(diary.index['objects']),10)


if __name__=='__main__':
    unittest.main()
