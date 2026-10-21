"""Añade un tope mensual al contador diario existente, sin reiniciarlo."""
import utilidades as U


class DiarioMensual(U.PresupuestoDiario):
    def __init__(self, nombre, diario, mensual, desde, reserva=0):
        super().__init__(nombre, diario, reserva)
        self.mensual, self.desde = mensual, desde
        self.archivo_mes = 'presupuesto_'+nombre+'_mensual.json'
        raw=U.cargar_json(self.archivo_mes,{})
        mes=self._hoy()[:7]
        self.mes=mes
        self.usadas_mes=max(0,int(raw.get('usadas',0))) if raw.get('mes')==mes else self.usadas
        self.completo=bool(raw.get('completo')) if raw.get('mes')==mes else self._hoy().endswith('-01')
        self._guardar_mes()

    def _rotar_mes(self):
        mes=self._hoy()[:7]
        if mes!=self.mes:
            self.mes,self.usadas_mes,self.completo=mes,0,True

    def _guardar_mes(self):
        U.guardar_json(self.archivo_mes,{'mes':self.mes,'usadas':self.usadas_mes,'completo':self.completo})

    def restantes(self):
        diario=super().restantes()
        self._rotar_mes()
        return min(diario,max(0,self.mensual-self.usadas_mes)) if self._hoy()>=self.desde else diario

    def registrar(self,n=1,restantes_reales=None):
        self._rotar_mes()
        antes=self.usadas
        super().registrar(n,restantes_reales)
        self.usadas_mes+=n
        if restantes_reales is not None and self.usadas-antes>n:
            self.completo=False # otros usos de la clave no se reconstruyen como consumo mensual conocido
        self._guardar_mes()

    def estado_mensual(self):
        self._rotar_mes()
        return {'mes_utc':self.mes,'usadas_mes_observadas':self.usadas_mes,
                'limite_mes':self.mensual,'limite_mes_desde':self.desde,
                'contador_mes_bot_completo':self.completo,
                'limite_mes_activo':self._hoy()>=self.desde}
