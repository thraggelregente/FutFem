"""Cobertura observada; no equivale al universo de partidos femeninos."""
from collections import Counter
from auditoria_decisiones import contexto


class Cobertura:
    def __init__(self):
        self.observaciones = Counter()
        self.consultas = {}
        self.eventos = {}
        self.decisiones = {}
        self.truncados = Counter()
        self.deliveries = Counter()

    def consulta(self, fuente, deporte, count, error=None):
        self.consultas[fuente + ':' + deporte] = {'normalized_rows': count, 'error': error, 'empty_means':'no_normalized_rows; consult_http_and_budget_status' if not count and not error else None}
        self.observaciones[fuente + ':' + deporte] += count

    def truncado(self, fuente, deporte):
        self.truncados[fuente + ':' + deporte] += 1

    def evento(self, key, ev):
        self.eventos[key] = ev

    def decision(self, key, state, reason, result=None):
        self.decisiones[key] = {'state': state, 'reason': reason, 'evaluated': result is not None}

    def entrega(self, destination_role, ok):
        self.deliveries[destination_role + (':complete' if ok else ':failed')] += 1

    def resumen(self):
        deportes, competiciones = {}, {}
        for key, ev in self.eventos.items():
            sport = ev.get('deporte', 'unknown')
            row = deportes.setdefault(sport, {'unique_events': 0, 'sources_observed': [], 'states': {}, 'exclusive_events': {}})
            row['unique_events'] += 1
            sources = sorted(set(ev.get('_fuentes_detectadas') or [ev.get('fuente', 'unknown')]))
            row['sources_observed'] = sorted(set(row['sources_observed']) | set(sources))
            if len(sources) == 1:
                row['exclusive_events'][sources[0]] = row['exclusive_events'].get(sources[0], 0) + 1
            dec = self.decisiones.get(key, {'state': 'pending', 'reason': 'queue'})
            label = dec['state'] + ':' + dec['reason']
            row['states'][label] = row['states'].get(label, 0) + 1
            ctx = contexto(ev)
            group = '|'.join(str(ctx[k]) for k in ('sport', 'competition_id', 'season', 'category', 'format'))
            comp = competiciones.setdefault(group, dict(ctx, unique_events=0, evaluated=0, reasons={}))
            comp['unique_events'] += 1
            comp['evaluated'] += int(dec.get('evaluated', False))
            comp['reasons'][label] = comp['reasons'].get(label, 0) + 1
        return {'scope': 'observed_feeds_only', 'sports': deportes, 'competitions': list(competiciones.values())[:150],
                'competitions_omitted': max(0, len(competiciones)-150), 'normalized_observations': dict(self.observaciones),
                'queries': self.consultas, 'truncated_pages': dict(self.truncados),
                'deliveries_by_role': dict(self.deliveries), 'coverage_percentage': None}


actual = Cobertura()

def iniciar():
    global actual
    actual = Cobertura()
    return actual
