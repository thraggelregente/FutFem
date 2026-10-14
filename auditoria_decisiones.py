"""Diario inmutable y acotado. No guarda credenciales ni datos de mercados."""
import base64
import hashlib
import json
import os
import time
import zlib
from datetime import datetime, timezone
import utilidades as U

REVISION = 'radar-evaluation-v2'
TTL = 90 * 86400
MAX_RECORDS = 10000
MAX_BYTES = 100_000_000
MAX_COMMANDS_MONTH = 90000
MAX_TRANSFER_MONTH = 3_000_000_000
SENSITIVE = ('token', 'authorization', 'api_key', 'apikey', 'chat_id', 'odds', 'bookmaker', 'prematchodds', 'prediction', 'k1', 'k2', 'odd1', 'odd2')


def limpio(value):
    if isinstance(value, dict):
        return {str(k): limpio(v) for k, v in value.items()
                if not any(s in str(k).lower() for s in SENSITIVE)}
    if isinstance(value, (list, tuple)):
        return [limpio(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def serializar(value):
    return json.dumps(limpio(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(serializar(value).encode()).hexdigest()


def empaquetar(value):
    return base64.b64encode(zlib.compress(serializar(value).encode(), 6)).decode()


def desempaquetar(value):
    return json.loads(zlib.decompress(base64.b64decode(value)))


def contexto(ev):
    liga = ev.get('contexto_competicion') or ev.get('liga_ref') or ev.get('wta_torneo')
    nombres = [str((ev.get(l) or {}).get('nombre') or '') for l in ('local', 'visita')]
    categorias = [U.categoria_equipo(n) for n in nombres + [str(ev.get('torneo') or '')]]
    juveniles = sorted({edad for edades, _ in categorias for edad in edades})
    categoria = 'women_u' + '-'.join(juveniles) if juveniles else 'women_reserve' if any(r for _, r in categorias) else 'women_age_unknown'
    return {'sport': ev.get('deporte'), 'competition_id': liga or 'unknown',
            'competition': ev.get('torneo'), 'season': ev.get('season_ref') or ev.get('temporada_cricket') or
            (ev.get('wta_torneo') or [None, None])[-1] or 'unknown', 'category': categoria,
            'format': ev.get('formato_cricket') or ('singles' if ev.get('deporte') == 'Tennis' else 'unknown')}


def _material(value):
    """El reloj de cada barrido no constituye un cambio de evidencia deportiva."""
    if isinstance(value,dict):
        return {k:_material(v) for k,v in value.items() if k not in ('evaluation_at_utc','inputs_observed_at_utc')}
    if isinstance(value,list):
        return [_material(v) for v in value]
    return value


class Diario:
    def __init__(self, nombre='evaluacion_v1', clock=time.time):
        self.nombre, self.clock = nombre, clock
        self.index = U.cargar_json(nombre + '_index.json', {})
        if not isinstance(self.index, dict):
            self.index = {}
        self.index.setdefault('objects', {})
        self.index.setdefault('latest', {})
        self.index.setdefault('commands', {})
        self.index.setdefault('transfer_bytes', {})
        self.pending = {}
        self.dirty = False
        self.persistence = 'unknown'
        self.errors = 0
        self.omitted = 0
        self._prune()

    def _prune(self):
        limite = self.clock() - TTL
        objects = self.index['objects']
        expired = {k for k, v in objects.items() if v['ts'] < limite}
        for k in expired:
            objects.pop(k)
            self.pending.pop(k,None)
            if not U.usa_upstash():
                try:
                    os.remove(os.path.join(U.DATA_DIR,self.nombre+"_"+k+".json"))
                except OSError:
                    pass
        self.index['latest'] = {k: v for k, v in self.index['latest'].items() if v in objects}
        if expired:
            self.dirty = True
        mes = datetime.fromtimestamp(self.clock(), timezone.utc).strftime('%Y-%m')
        self.index['commands'] = {mes: self.index['commands'].get(mes, 0)}
        self.index['transfer_bytes'] = {mes:self.index['transfer_bytes'].get(mes,0)}
        return mes

    def guardar(self, tipo, value, evidence=None, material=None):
        self._prune()
        value = limpio(value)
        evidence = limpio(evidence or {})
        stable = {'record': value, 'evidence': evidence}
        # Instante y entrega son metadatos de la nueva versión, no el criterio de reescritura.
        for field in ('observed_at_utc', 'snapshot_id', 'persistence'):
            stable['record'].pop(field, None)
        fingerprint = digest(material if material is not None else _material(stable))
        entity = tipo + ':' + str(value.get('event_key') or value.get('outcome_key') or fingerprint)
        old = self.index['latest'].get(entity)
        if old and self.index['objects'].get(old, {}).get('fingerprint') == fingerprint:
            return old
        sid = digest([entity, fingerprint, old])
        value.update(schema_version=1, observed_at_utc=self.clock(), revision_motor=REVISION,
                     snapshot_id=sid, previous_snapshot=old)
        ref = digest(evidence) if evidence else None
        value['history_snapshot_refs'] = [ref] if ref else []
        payloads = {sid: empaquetar({'type': tipo, 'record': value})}
        if ref:
            payloads[ref] = empaquetar({'type': 'evidence', 'data': evidence})
        size = sum(len(v.encode()) for v in payloads.values())
        mes = self._prune()
        total = sum(v['bytes'] for v in self.index['objects'].values())
        # No desalojar evidencia referida por una decisión todavía retenida.
        if (len(self.index['objects']) + len(set(payloads)-set(self.index['objects'])) > MAX_RECORDS or total + size > MAX_BYTES
                or self.index['commands'].get(mes, 0) + len(self.pending) + len(payloads) + 2 >= MAX_COMMANDS_MONTH):
            self.omitted += 1
            return None
        for key, payload in payloads.items():
            self.pending[key] = payload
            self.index['objects'][key] = {'ts': self.clock(), 'bytes': len(payload.encode()),
                                         'type': tipo if key == sid else 'evidence', 'fingerprint': fingerprint}
        if ref:
            # Dependencia viva: conservar el objeto durante toda la retención de su consumidor.
            self.index['objects'][ref]['ts'] = self.clock()
        self.index['latest'][entity] = sid
        self.dirty = True
        return sid

    def leer(self, sid):
        payload = self.pending.get(sid)
        if payload is None:
            if U.usa_upstash():
                try:
                    payload = self._redis(['GET', f'radar:{self.nombre}:{sid}'])
                except Exception:
                    self.errors += 1
            if payload is None:
                payload = U.cargar_json(self.nombre + '_' + sid + '.json', None) if not U.usa_upstash() else self._local(sid)
        return desempaquetar(payload) if payload else None

    def _local(self, sid):
        try:
            with open(os.path.join(U.DATA_DIR, self.nombre + '_' + sid + '.json'), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _redis(self, command):
        mes = self._prune()
        estimated=len(serializar(command).encode())
        if self.index['commands'].get(mes, 0) >= MAX_COMMANDS_MONTH or self.index['transfer_bytes'].get(mes,0)+estimated>MAX_TRANSFER_MONTH:
            raise RuntimeError('audit_command_budget')
        self.index['commands'][mes] = self.index['commands'].get(mes, 0) + 1
        self.index['transfer_bytes'][mes]=self.index['transfer_bytes'].get(mes,0)+estimated
        response=U._upstash(command)
        self.index['transfer_bytes'][mes]+=len(serializar(response).encode())
        return response

    def flush(self):
        if not self.dirty:
            return
        failed = False
        pendientes=list(self.pending.items())
        for offset in range(0,len(pendientes),20):
            batch=pendientes[offset:offset+20]
            ok=[False]*len(batch)
            try:
                if U.usa_upstash():
                    commands=[['SET',f'radar:{self.nombre}:{sid}',payload,'EX',TTL]+
                              ([] if self.index['objects'][sid]['type']=='evidence' else ['NX']) for sid,payload in batch]
                    mes=self._prune()
                    size=len(serializar(commands).encode())
                    if self.index['commands'].get(mes,0)+len(commands)+1>MAX_COMMANDS_MONTH or self.index['transfer_bytes'].get(mes,0)+size>MAX_TRANSFER_MONTH:
                        raise RuntimeError('audit_budget')
                    self.index['commands'][mes]=self.index['commands'].get(mes,0)+len(commands)
                    self.index['transfer_bytes'][mes]=self.index['transfer_bytes'].get(mes,0)+size
                    ok=U._upstash_pipeline(commands)
                else:
                    ok=[U.guardar_json(self.nombre+'_'+sid+'.json',payload) for sid,payload in batch]
            except Exception:
                pass
            for (sid,payload),success in zip(batch,ok):
                if success:
                    self.pending.pop(sid,None)
                    continue
                failed=True
                self.errors+=1
                try:
                    os.makedirs(U.DATA_DIR,exist_ok=True)
                    with open(os.path.join(U.DATA_DIR,self.nombre+'_'+sid+'.json'),'w',encoding='utf-8') as f:
                        json.dump(payload,f)
                except OSError:
                    pass
        try:
            if U.usa_upstash():
                self._redis(['SET', f'radar:{self.nombre}_index.json', serializar(self.index), 'EX', TTL])
            elif not U.guardar_json(self.nombre + '_index.json', self.index):
                raise OSError('index_write_failed')
            self.persistence = 'volatile' if failed else 'durable' if U.usa_upstash() or U.persistencia_es_duradera() else 'volatile'
            self.dirty = failed
        except Exception:
            self.persistence = 'failed'
            self.errors += 1

    def registros(self, tipo='decision'):
        for sid, meta in list(self.index['objects'].items()):
            if meta['type'] != tipo:
                continue
            obj = self.leer(sid)
            if obj:
                record = obj['record']
                refs = record.get('history_snapshot_refs') or []
                evidencia = self.leer(refs[0]) if refs else None
                yield dict(record, evidence=(evidencia or {}).get('data', {}))

    def estado(self):
        return {'persistence': self.persistence, 'records_and_evidence': len(self.index['objects']),
                'bytes_compressed': sum(v['bytes'] for v in self.index['objects'].values()),
                'commands_month': sum(self.index['commands'].values()), 'commands_limit_month': MAX_COMMANDS_MONTH,
                'transfer_bytes_month_estimated':sum(self.index['transfer_bytes'].values()),
                'transfer_limit_month':MAX_TRANSFER_MONTH, 'pending_writes': len(self.pending), 'errors': self.errors, 'omitted_capacity': self.omitted,
                'retention_days': TTL // 86400}


_diario = None

def diario():
    global _diario
    if _diario is None:
        _diario = Diario()
    return _diario


def registrar(ev, key, decision, reason, inputs=None, result=None, delivery=None):
    try:
        ts = time.time()
        kickoff = ev.get('startTimestamp')
        observed = [{k: o.get(k) for k in ('fuente', 'id', 'liga_ref', 'contexto_competicion', 'wta_torneo', 'startTimestamp')}
                    for o in ev.get('_observaciones') or [ev]]
        record = dict(contexto(ev), event_key=key, kickoff_utc=kickoff,
                      kickoff_precision=ev.get('fecha_precision', 'exact' if kickoff else 'unknown'),
                      participants=[ev.get(l) or {} for l in ('local', 'visita')],
                      provider_observations=observed, decision=decision, reason_codes=[reason],
                      score=(result or {}).get('puntaje'), favoured_participant_id=(result or {}).get('favorito'),
                      signals=(result or {}).get('signals') or (result or {}).get('evidencia') or (result or {}).get('alertas') or [],
                      data_quality=(result or {}).get('calidad') or (result or {}).get('calidad_datos'),
                      pre_match=bool(kickoff and ts < kickoff), delivery=delivery,
                      persistence=diario().persistence)
        return diario().guardar('decision', record, {'event': ev, 'inputs': inputs or {}, 'result': result or {}})
    except Exception as exc:
        U.log('[audit] registro omitido: ' + type(exc).__name__)
        return None
