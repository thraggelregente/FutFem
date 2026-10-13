import datetime
from collections import defaultdict
import utilidades as U

ARCHIVO_COBERTURA = "cobertura_eventos.json"

_datos = {}
_cargado = False

def _cargar():
    global _datos, _cargado
    if not _cargado:
        crudo = U.cargar_json(ARCHIVO_COBERTURA, {})
        if isinstance(crudo, dict):
            _datos = crudo
        _cargado = True

def registrar(clave, estado, deporte, torneo):
    _cargar()

    jerarquia = {
        "identidad_no_fiable": 1,
        "sin_ranking": 2,
        "sin_historial": 5,
        "evaluado": 4
    }

    actual = _datos.get(clave)
    nuevo_nivel = jerarquia.get(estado, 0)

    if actual:
        nivel_actual = jerarquia.get(actual.get("estado"), 0)
        if nuevo_nivel <= nivel_actual:
            return  # Mantenemos el estado actual si es de igual o mayor jerarquía (e.g. evaluado > sin_historial)

    _datos[clave] = {
        "estado": estado,
        "deporte": deporte or "Desconocido",
        "torneo": torneo or "Desconocido",
        "actualizado_iso": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

def podar(dias=7):
    _cargar()
    global _datos

    limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=dias)
    limpio = {}
    for clave, valor in _datos.items():
        try:
            f = U._parsear_iso(valor.get("actualizado_iso"))
            if f is not None and f >= limite:
                limpio[clave] = valor
        except Exception:
            pass
    _datos = limpio

def guardar():
    _cargar()
    U.guardar_json(ARCHIVO_COBERTURA, _datos)

def reporte():
    _cargar()
    resumen = defaultdict(lambda: defaultdict(int))
    total = 0

    for info in _datos.values():
        total += 1
        deporte = info.get("deporte", "Desconocido")
        torneo = info.get("torneo", "Desconocido")
        estado = info.get("estado", "desconocido")

        # Agrupamos por deporte
        resumen[deporte][estado] += 1
        resumen[deporte]["total"] += 1

        # Y también guardamos el detalle por torneo dentro del deporte (clave compuesta)
        resumen[f"{deporte}|{torneo}"][estado] += 1
        resumen[f"{deporte}|{torneo}"]["total"] += 1

    return {
        "total_eventos": total,
        "detalle": {k: dict(v) for k, v in resumen.items()}
    }
