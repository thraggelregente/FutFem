"""FIVB VIS: vóley femenino público, fechas UTC y torneos verificados por fila."""
import os
import re
import time
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

import utilidades as U
from fuentes_publicas import Cliente, enteros, fechas_validas, instante_utc, xml_seguro

FUENTE = "fivb"
ACTIVO = os.environ.get("FIVB_ACTIVO", "1") != "0"
_cache = U.CachePersistente("fivb_v1", 6 * 3600, max_items=96)
cliente = Cliente(FUENTE, _cache)
presupuesto = cliente.presupuesto
_historial = []
_pool_calls=0
_pool_seen=set()
_estado_tablas={"verified":0,"rejected":0}


def disponible():
    return ACTIVO


def normalizar(nodo, ahora=None):
    ahora = time.time() if ahora is None else ahora
    raw, torneo = nodo.attrib, nodo.find("Tournament")
    if not str(raw.get("No", "")).isdigit() or not str(raw.get("NoTournament", "")).isdigit():
        return None
    if torneo is None or torneo.get("Gender") not in ("1", "W"):
        return None  # nunca confiar solamente en TournamentGenders del pedido
    torneo = torneo.attrib
    if torneo.get("No") != raw.get("NoTournament"):
        return None
    ts = instante_utc(raw.get("DateTimeUtc"))
    if not fechas_validas(ts, torneo.get("StartDate"), torneo.get("EndDate")):
        return None
    nums = enteros(raw.get("NoTeamA"), raw.get("NoTeamB"), raw.get("Status"))
    if not nums or min(nums[:2]) <= 0 or nums[0] == nums[1]:
        return None
    na, nb = raw.get("TeamAName", ""), raw.get("TeamBName", "")
    if not all(U.participante_definido(n) for n in (na, nb)):
        return None
    # El nombre del país puede ser idéntico en mayores y juveniles.
    edades = re.findall(r"\bU[ -]?(\d{2})\b", torneo.get("Name", ""), re.I)
    sufijo = " U" + edades[0] if edades else ""
    contexto = f"fivb:{raw.get('NoTournament')}"
    comunes = {"deporte": "Volleyball", "fuente": FUENTE, "contexto_competicion": contexto,
               "historial_aislado": True, "fivb_pool": raw.get("NoPool"),
               "fivb_start":torneo.get("StartDate"), "fivb_end":torneo.get("EndDate"), "torneo": torneo.get("Name", "Vóley femenino FIVB"),
               "femenino_seguro": True, "startTimestamp": ts,
               "local": {"id": f"fivb:{nums[0]}", "nombre": na + sufijo},
               "visita": {"id": f"fivb:{nums[1]}", "nombre": nb + sufijo}}
    if 1 <= nums[2] <= 4 and ahora < ts <= ahora + 86400:
        return dict(comunes, id="fivb_" + raw["No"], tipo_estado="pre", horario=U.formatear_hora_arg(ts))
    scores = enteros(raw.get("MatchPointsA"), raw.get("MatchPointsB"))
    if (nums[2] not in (24, 25, 26, 27) or not ahora - 90 * 86400 <= ts < ahora
            or not scores or max(scores) != 3 or min(scores) not in (0, 1, 2)
            or raw.get("ResultType") != "0"):
        return None
    puntos_set=[]
    for i in range(1,6):
        puntos=enteros(raw.get(f'PointsTeamASet{i}'),raw.get(f'PointsTeamBSet{i}'))
        if puntos and max(puntos)>0:
            puntos_set.append(list(puntos))
    from voley_oficial import _puntos_validos
    if not _puntos_validos(puntos_set,list(scores)):
        puntos_set=[]
    return dict(comunes, puntos_por_set=puntos_set, id="fivb_" + raw["No"], _outcome_status="normal", fecha=U.ts_a_iso_utc(ts), id_local=comunes["local"]["id"],
                id_visita=comunes["visita"]["id"], nom_local=na + sufijo, nom_visita=nb + sufijo,
                puntos_local=scores[0], puntos_visita=scores[1])


def obtener_eventos(deporte):
    global _historial
    if deporte != "Volleyball" or not disponible():
        return []
    now = datetime.now(timezone.utc)
    desde, hasta = (now - timedelta(days=90)).date().isoformat(), (now + timedelta(days=2)).date().isoformat()
    req = ET.Element("Request", Type="GetVolleyMatchList", Fields="No NoTournament NoPool DateTimeUtc Status TeamAName TeamBName NoTeamA NoTeamB MatchPointsA MatchPointsB ResultType " + " ".join(f"PointsTeam{side}Set{i}" for side in "AB" for i in range(1,6)))
    ET.SubElement(req, "Filter", FirstDate=desde, LastDate=hasta, TournamentGenders="W")
    ET.SubElement(req, "Relation", Name="Tournament", Fields="Name Gender StartDate EndDate")
    texto = cliente.pedir("https://www.fivb.org/Vis2009/XmlRequest.asmx", {"Request": ET.tostring(req, encoding="unicode")}, xml=True)
    root = xml_seguro(texto)
    if root is None or root.tag != "VolleyballMatches":
        return []
    registros = [p for p in (normalizar(n, now.timestamp()) for n in root) if p]
    _historial = [p for p in registros if "fecha" in p]
    eventos = [p for p in registros if p.get("tipo_estado") == "pre"]
    U.log(f"[fivb] {len(eventos)} próximos y {len(_historial)} resultados normales con fecha verificada")
    return eventos


def historial_equipo(evento, lado):
    tid = (evento.get(lado) or {}).get("id")
    contexto = evento.get("contexto_competicion")
    return sorted((p for p in _historial if p.get("contexto_competicion") == contexto and
                   tid in (p["id_local"], p["id_visita"])), key=lambda p: p["fecha"], reverse=True)[:10]


def resultados_evaluacion(evento):
    """Reutiliza el listado verificado cargado por el calendario."""
    if evento.get("deporte") != 'Volleyball':
        return []
    from resultados_evaluacion import de_historial
    return [r for p in _historial if (r := de_historial(p, 'Volleyball', FUENTE))]


def iniciar_ciclo():
    global _pool_calls
    _pool_calls=0
    _pool_seen.clear()
    _estado_tablas.update(verified=0,rejected=0)


def _xml(tipo,fields,**attrs):
    req=ET.Element('Request',Type=tipo,Fields=fields,**{k:str(v) for k,v in attrs.items()})
    return xml_seguro(cliente.pedir('https://www.fivb.org/Vis2009/XmlRequest.asmx',
                                   {'Request':ET.tostring(req,encoding='unicode')},ttl=6*3600,xml=True))


def normalizar_tabla(root,evento,historial,ahora=None):
    """La tabla debe reconciliar TODOS sus contadores con resultados de la edición."""
    ahora=time.time() if ahora is None else ahora
    if root is None or root.tag!='VolleyballPoolRankings':
        return None,0
    inicio=instante_utc(evento.get('fivb_start'))
    fin=instante_utc(evento.get('fivb_end'))
    if not inicio or not fin or not 0<=ahora-inicio<=90*86400 or fin<evento.get('startTimestamp',0)-86400:
        return None,0 # Una ventana de 90 días no acredita la tabla de una temporada más larga.
    pool=str(evento.get('fivb_pool') or '')
    contexto=evento.get('contexto_competicion')
    games={p['id']:p for p in historial if p.get('contexto_competicion')==contexto and str(p.get('fivb_pool'))==pool}
    contadores={}
    for p in games.values():
        for side,other in (('local','visita'),('visita','local')):
            tid=str(p['id_'+side]); row=contadores.setdefault(tid,{'wins':0,'losses':0,'sets':0})
            propios=p['puntos_'+side]; rivales=p['puntos_'+other]
            row['wins' if propios>rivales else 'losses']+=1
            row['sets']+=propios-rivales
    tabla={}
    for nodo in root:
        raw=nodo.attrib
        values=enteros(raw.get('NoTeam'),raw.get('Position'),raw.get('MatchesWon'),raw.get('MatchesLost'),raw.get('SetsWon'),raw.get('SetsLost'))
        if not values or str(raw.get('NoPool'))!=pool or min(values)<0:
            return None,0
        tid,pos,w,l,sw,sl=values
        key='fivb:'+str(tid)
        if key in tabla or not tid or not pos:
            return None,0
        observed=contadores.get(key,{'wins':0,'losses':0,'sets':0})
        if (w,l,sw-sl)!=(observed['wins'],observed['losses'],observed['sets']):
            return None,0
        tabla[key]={'posicion':pos,'victorias':w,'derrotas':l,'empates':0,'dif_neta':sw-sl,
                    'fuente':FUENTE,'edicion':contexto,'grupo':pool}
    if len(tabla)<2 or sorted(row['posicion'] for row in tabla.values())!=list(range(1,len(tabla)+1)):
        return None,0
    ids=[(evento.get(l) or {}).get('id') for l in ('local','visita')]
    return (tabla,len(tabla)) if all(i in tabla for i in ids) else (None,0)


def tabla_partido(evento):
    global _pool_calls
    pool=evento.get('fivb_pool')
    if evento.get('fuente')!=FUENTE or not str(pool or '').isdigit():
        return None,0
    if str(pool) not in _pool_seen:
        if _pool_calls>=2:return None,0
        _pool_seen.add(str(pool))
        _pool_calls+=1
    meta=_xml('GetVolleyPool','No NoTournament',No=pool)
    expected=str(evento.get('contexto_competicion') or '').removeprefix('fivb:')
    if meta is None or meta.tag!='VolleyballPool' or str(meta.get('NoTournament'))!=expected or str(meta.get('No'))!=str(pool):
        _estado_tablas['rejected']+=1
        return None,0
    root=_xml('GetVolleyPoolRanking','NoTeam NoPool Position MatchesWon MatchesLost SetsWon SetsLost',NoPool=pool)
    tabla,cantidad=normalizar_tabla(root,evento,_historial)
    _estado_tablas['verified' if tabla else 'rejected']+=1
    return tabla,cantidad


def estado_contexto():
    return dict(_estado_tablas,table_attempts_cycle=_pool_calls)
