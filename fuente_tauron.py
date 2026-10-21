"""TAURON Liga Kobiet: edición actual del sitio femenino oficial de Polonia."""
import html
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import utilidades as U
from fuentes_publicas import Cliente
from voley_oficial import Oficial, numero, temporada_actual

FUENTE = "tauron"
ACTIVO = os.environ.get("TAURON_ACTIVO", "1") != "0"
BASE = "https://www.tauronligakobiet.pl"


def _texto(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _edicion(text, now):
    title = re.search(r"<title\b[^>]*>(.*?)</title>", text or "", re.S | re.I)
    if not title:
        return None
    title = _texto(title.group(1))
    season = re.search(r"Sezon (\d{4}/\d{4}) - TAURON Liga Kobiet$", title)
    return season.group(1) if season and season.group(1) == temporada_actual(now) else None


class Tauron(Oficial):
    def __init__(self):
        super().__init__(FUENTE)
        self.cliente = Cliente(FUENTE, self.cache, limite=24)

    def resolver(self, nombre):
        key = U.firma_equipo(nombre)
        if key in self.tabla:
            return key
        # Alias explícitos; no se aceptan coincidencias por ciudad o similitud difusa.
        aliases = {
            "developres rzeszow": "KS DevelopRes Rzeszow",
            "rzeszow": "KS DevelopRes Rzeszow",
            "chemik police": "LOTTO Chemik Police",
            "budowlani lodz": "PGE Budowlani Lodz",
            "bielsko biala": "BKS ZGO Bielsko Biala",
            "radomka radom": "MOYA Radomka Radom",
            "mks kalisz": "NETLAND MKS Kalisz",
            "palac bydgoszcz": "Metalkas Palac Bydgoszcz",
            "stal mielec": "ITA TOOLS STAL Mielec",
            "lks lodz": "LKS Commercecon Lodz",
        }
        target = aliases.get(U.normalizar(nombre).replace(" women", "").strip())
        resolved = U.firma_equipo(target) if target else None
        return resolved if resolved in self.tabla else None

    def tabla_para_evento(self, ev):
        if ev.get("deporte") != "Volleyball" or not self.edicion:
            return None, 0
        if any(U.categoria_equipo(str(v)) != ((), False) for v in
               [ev.get("torneo", "")] + [(ev.get(s) or {}).get("nombre", "") for s in ("local", "visita")]):
            return None, 0
        if ev.get("fuente") == FUENTE:
            if ev.get("contexto_competicion") != self.edicion:
                return None, 0
        else:
            name = U.normalizar(ev.get("torneo", ""))
            if not re.search(r"tauron|liga kobiet|liga siatkowki kobiet", name) or re.search(r"cup|puchar|cev|champions|1[. ]liga|division 2", name):
                return None, 0
        ids = [self.resolver((ev.get(s) or {}).get("nombre", "")) for s in ("local", "visita")]
        if not all(ids) or ids[0] == ids[1]:
            return None, 0
        return {ev[s]["id"]: self.tabla[key] for s, key in zip(("local", "visita"), ids)}, len(self.tabla)

    def cargar(self, table_text, games_text, now=None):
        now = time.time() if now is None else now
        season = _edicion(table_text, now)
        if not season or _edicion(games_text, now) != season:
            return False
        # El HTML conserva tablas de todas las jornadas: sólo filas visibles de la actual.
        block = re.search(r'<table\b[^>]*id="rs-standings-table-[^"]+"[^>]*>(.*?)</table>', table_text, re.S)
        if not block:
            return False
        rows = re.findall(r'<tr\b([^>]*)>(.*?)</tr>', block.group(1), re.S)
        tabla, names = {}, {}
        for attrs, row in rows:
            classes = re.search(r'class="([^"]*)"', attrs)
            if not re.search(r'\bdata-teamname=', attrs) or classes and "hidden" in classes.group(1).split():
                continue
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)
            if len(cells) != 18:
                return False
            values = [_texto(c) for c in cells]
            team = re.search(r"/teams/id/(\d+)\.html", cells[1])
            ints = [numero(values[i]) for i in (0, 2, 3, 4, 5, 6, 7, 8, 9)]
            if not team or None in ints:
                return False
            pos, points, played, won, lost, sw, sl, pf, pa = ints
            if played != won + lost or not pos or sw < won * 3 or sl < lost * 3:
                return False
            key = U.firma_equipo(values[1])
            if key in tabla or team.group(1) in names:
                return False
            names[team.group(1)] = key
            tabla[key] = dict(nombre=values[1], posicion=pos, victorias=won, derrotas=lost,
                              empates=0, dif_neta=sw-sl, fuente=FUENTE, season=season,
                              points_for=pf, points_against=pa, team_ref=team.group(1))
        if len(tabla) < 6 or sorted(r["posicion"] for r in tabla.values()) != list(range(1, len(tabla)+1)):
            return False
        history, events, seen = [], [], set()
        edition = "tauron:" + season
        for attrs, body in re.findall(r'<section\b([^>]*\bdata-game-id="\d+"[^>]*)>(.*?)</section>', games_text, re.S):
            if not re.search(r'\bfilterable-content-RS\b', attrs):
                continue
            mid = re.search(r'data-game-id="(\d+)"', attrs).group(1)
            teams = re.search(r'data-team="(\d+),(\d+)"', attrs)
            date = re.search(r'\b(\d{2}\.\d{2}\.\d{4}),\s*(\d{2}:\d{2})\b', body)
            if mid in seen or not teams or not date:
                continue
            seen.add(mid)
            if not all(t in names for t in teams.groups()) or teams[1] == teams[2]:
                continue
            a, b = [names[t] for t in teams.groups()]
            labels = re.findall(r'<div\b[^>]*class="[^"]*\bgame-team\b[^"]*"[^>]*>(.*?)</div>', body, re.S)
            if len(labels) != 2 or [U.firma_equipo(_texto(n)) for n in labels] != [a, b]:
                continue
            try:
                local = datetime.strptime(" ".join(date.groups()), "%d.%m.%Y %H:%M")
                zone = ZoneInfo("Europe/Warsaw")
                # Una hora ambigua o inexistente por DST no acredita un kickoff exacto.
                if local.replace(tzinfo=zone, fold=0).utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset():
                    continue
                ts = int(local.replace(tzinfo=zone).timestamp())
            except ValueError:
                continue
            if temporada_actual(ts) != season or re.search(r"walkover|walk.over|odwoł|przełoż|forfeit|w\.o\.", _texto(body), re.I):
                continue
            scores = [re.search(r'data-synced-games-content="setsTeam'+side+r'"[^>]*>([^<]*)</span>', body) for side in "AB"]
            score = [numero(x.group(1)) if x else None for x in scores]
            common = dict(id="tauron_"+mid, fuente=FUENTE, deporte="Volleyball", torneo="TAURON Liga Kobiet (Poland)",
                          contexto_competicion=edition, season_ref=season, femenino_seguro=True,
                          historial_aislado=True, startTimestamp=ts,
                          local={"id":"tauron:"+a,"nombre":tabla[a]["nombre"]},
                          visita={"id":"tauron:"+b,"nombre":tabla[b]["nombre"]})
            if now < ts <= now + 86400 and (None in score or score == [0, 0]):
                events.append(dict(common, tipo_estado="pre", horario=U.formatear_hora_arg(ts)))
            elif ts < now and None not in score and max(score) == 3 and min(score) in (0, 1, 2):
                history.append(dict(common, fecha=U.ts_a_iso_utc(ts), id_local=common["local"]["id"],
                                    id_visita=common["visita"]["id"], nom_local=tabla[a]["nombre"], nom_visita=tabla[b]["nombre"],
                                    puntos_local=score[0], puntos_visita=score[1], _outcome_status="normal"))
        # Reconciliar la tabla con todos los terminados de la edición evita tablas antiguas.
        for key, row in tabla.items():
            tid = "tauron:"+key
            games = [p for p in history if tid in (p["id_local"], p["id_visita"])]
            won = sum((p["puntos_local"] > p["puntos_visita"]) == (p["id_local"] == tid) for p in games)
            diff = sum((p["puntos_local"]-p["puntos_visita"]) * (1 if p["id_local"] == tid else -1) for p in games)
            if (won, len(games)-won, diff) != (row["victorias"], row["derrotas"], row["dif_neta"]):
                return False
        recent = [p for p in history if now-p['startTimestamp'] <= 90*86400]
        self.edicion, self.tabla, self.historial, self.eventos = edition, tabla, recent, events
        self.status.update(state="verified_table_and_results", edition=edition, teams=len(tabla), history=len(recent), events=len(events))
        return True


oficial = Tauron()
_cache = oficial.cache
presupuesto = oficial.cliente.presupuesto


def disponible():
    return ACTIVO


def obtener_eventos(deporte):
    if deporte != "Volleyball" or not disponible():
        return []
    table = oficial.cliente.pedir(BASE+"/table/nocookies/1.html", xml=True)
    games = oficial.cliente.pedir(BASE+"/games/nocookies/1.html", xml=True)
    if not oficial.cargar(table or "", games or ""):
        oficial.tabla, oficial.historial, oficial.eventos = {}, [], []
        oficial.status.update(state="rejected_schema_season_or_reconciliation", teams=0, history=0, events=0)
    return list(oficial.eventos)


def tabla_partido(ev):
    return oficial.tabla_para_evento(ev) if disponible() else (None, 0)


def historial_equipo(ev, lado):
    return oficial.historial_para_evento(ev, lado) if disponible() else []


def tiene_contexto(ev):
    return bool(tabla_partido(ev)[0])


def estado_contexto():
    return dict(oficial.status)


def resultados_evaluacion(ev):
    return oficial.resultados_para_evento(ev) if disponible() else []
