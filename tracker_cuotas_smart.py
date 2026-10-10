"""Compatibilidad segura: el radar está configurado en modo CERO CUOTAS.

Este módulo sustituye al tracker de mercados anterior. No hace requests, no lee
keys de proveedores de odds, no consulta casas de apuestas y no almacena cuotas.
Se conservan funciones públicas mínimas para evitar romper importaciones antiguas.
"""


def disponible():
    return False


def consultar_cuotas(*args, **kwargs):
    return []


def obtener_cuotas(*args, **kwargs):
    return []


def calcular_desplome(*args, **kwargs):
    return None


def ejecutar(*args, **kwargs):
    return {"activo": False, "motivo": "Modo CERO CUOTAS: monitor deshabilitado."}
