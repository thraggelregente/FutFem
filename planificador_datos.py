"""Reparto por urgencia, carencia y exploración; los adaptadores conservan sus cuotas."""
import hashlib
import time
from collections import Counter


def saldos_disponibles(presupuestos):
    """Un resumen de texto antiguo no certifica solicitudes disponibles."""
    salida = {}
    for source, row in presupuestos.items():
        if not isinstance(row, dict):
            continue
        try:
            salida[source] = max(0, int(row.get('disponibles_bot', 0)))
        except (TypeError, ValueError):
            salida[source] = 0
    return salida


class Planificador:
    def __init__(self):
        self.paused = {}
        self.stats = Counter()
        self.shadow = []
        self.claimed = set()

    def iniciar(self):
        self.stats.clear()
        self.shadow = []
        self.claimed.clear()

    def http(self, source, code, now=None):
        now = time.time() if now is None else now
        self.stats[source + ':http:' + str(code)] += 1
        if code in (401, 403, 429):
            self.paused[source] = max(self.paused.get(source, 0), now + (86400 if code in (401, 403) else 3600))

    def permitido(self, source, now=None):
        return self.paused.get(source, 0) <= (time.time() if now is None else now)

    def prioridad(self, task, now):
        deadline = task.get('deadline', now + 86400)
        cost = max(1, task.get('cost', 1))
        return (int(task.get('result_pending', False))*8 + int(task.get('missing', False))*4 +
                int(task.get('new_coverage', False))*2 + max(0, 3-(deadline-now)/28800)) / cost

    def seleccionar(self, tasks, budgets, now=None, limit=100):
        now = time.time() if now is None else now
        # 20% de huecos para el universo desconocido, de modo reproducible.
        valid = [t for t in tasks if t.get('deadline', now+1) > now and not t.get('cache_valid') and self.permitido(t['source'], now)]
        unknown = sorted((t for t in valid if t.get('new_coverage')), key=lambda t: hashlib.sha256(t['key'].encode()).hexdigest())
        ranked = sorted(valid, key=lambda t: (-self.prioridad(t, now), t['key']))
        candidates = unknown[:max(1, limit//5)] + ranked
        left = dict(budgets)
        selected, keys = [], set()
        for task in candidates:
            source, key, cost = task['source'], task['key'], max(1, task.get('cost', 1))
            if key in keys or key in self.claimed or left.get(source, 0) < cost:
                continue
            # Una sola bolsa por host/proveedor, aunque tenga varios deportes.
            left[source] -= cost
            selected.append(task)
            keys.add(key)
            if len(selected) >= limit:
                break
        self.shadow = [{'key': t['key'], 'source': t['source'], 'priority': round(self.prioridad(t, now), 3)} for t in selected]
        return selected

    def ordenar_eventos(self, events, last_attempt, key_fn, now=None):
        now = time.time() if now is None else now
        def order(ev):
            key = key_fn(ev)
            # Se conserva la rotación, con urgencia entre eventos todavía no intentados.
            return (last_attempt.get(key, 0), ev.get('startTimestamp') or now+86400, key)
        # Intercalar deportes mantiene la rotación dentro de cada uno e impide
        # que un calendario voluminoso consuma todos los análisis del ciclo.
        from collections import deque
        groups = {}
        for ev in sorted(events, key=order):
            groups.setdefault(ev.get('deporte', 'unknown'), deque()).append(ev)
        sports = sorted(groups, key=lambda s: (order(groups[s][0]), s))
        output = []
        while sports:
            active = []
            for sport in sports:
                output.append(groups[sport].popleft())
                if groups[sport]:
                    active.append(sport)
            sports = active
        return output

    def resumen(self):
        calls = sum(v for k,v in self.stats.items() if ':http:' in k)
        return {'mode': 'active_rotation_and_shared_host_pauses; task_allocation_shadow',
                'http_requests': calls, 'http_by_source_status': dict(self.stats),
                'paused_sources': sorted(k for k in self.paused if not self.permitido(k)),
                'shadow_tasks': self.shadow[:20], 'exploration_fraction': 0.2}


actual = Planificador()
