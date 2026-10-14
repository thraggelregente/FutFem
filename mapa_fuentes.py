"""Capacidades de las rutas realmente integradas, separadas de aportes observados."""

def construir(modules, espn_activo=True):
    sports=['Soccer','Basketball','Tennis','Ice Hockey','Handball','Volleyball','Rugby','Softball','Lacrosse','Field Hockey','Cricket']
    fixed={'sportscore':{'Soccer','Basketball','Tennis','Cricket'}, 'sportapi':{'Soccer'},
           'bbs':{'Basketball'},'balldontlie':{'Basketball'},'worldrugby':{'Rugby'},'wta':{'Tennis'},
           'pwhl':{'Ice Hockey'},'fivb':{'Volleyball'},'cev':{'Volleyball'},'openligadb':{'Soccer'},
           'cricsheet':{'Cricket'}, 'tennis_api':{'Tennis'}}
    scope={'bbs':'WNBA', 'balldontlie':'WNBA', 'pwhl':'PWHL', 'worldrugby':'XV femenino',
           'wta':'cuadros, historial y ranking oficiales; cobertura ITF limitada',
           'fivb':'torneos indoor VIS verificados', 'cev':'competiciones indoor europeas verificadas',
           'thesportsdb':'calendario de ligas configuradas; contexto por identidad verificada',
           'theoddsapi':'sólo competiciones femeninas de su catálogo activo',
           'oddspapi':'sólo torneos con evidencia femenina', 'espn':'allowlist femenina por liga',
           'cricsheet':'resultados publicados; sin calendario, clubes sin temporada no alertan',
           'tennis_api':'opcional; acceso y profundidad pendientes de key/suscripción'}
    output={sport:{'configured_sources':[], 'calendar_sources':[], 'context_only_sources':[], 'scopes':{}} for sport in sports}
    for name,module in modules.items():
        if not module or name=='espn' and not espn_activo:
            continue
        context_only=set()
        if name=='espn':
            enabled=set(module._ligas_configuradas())
            active=True
        elif name=='thesportsdb':
            active=module.disponible() or module.historial_disponible()
            enabled=set(module._LIGAS_FEMENINAS)
            if module.historial_disponible():
                # Main sólo utiliza este historial en deportes de equipos comerciales.
                context_only={'Soccer','Basketball','Ice Hockey','Handball','Volleyball','Rugby'}-enabled
        else:
            active=not hasattr(module,'disponible') or module.disponible()
            if not active:
                continue
            enabled=fixed[name] if name in fixed else set(getattr(module,'DEPORTES_ACTIVOS',[]))
        if not active:
            continue
        for sport in enabled | context_only:
            if sport not in output:
                continue
            # Las restricciones de main prevalecen sobre el soporte genérico de una API.
            if sport in {'Softball','Lacrosse','Field Hockey'} and name!='espn' or sport=='Cricket' and name not in {'sportscore','cricsheet'}:
                continue
            row=output[sport]
            row['configured_sources'].append(name)
            row['scopes'][name]=scope.get(name,'datos sujetos a identidad, vigencia y cobertura del feed')
            if sport in context_only or name=='cricsheet':
                row['context_only_sources'].append(name)
            else:
                row['calendar_sources'].append(name)
    for row in output.values():
        for key in ('configured_sources','calendar_sources','context_only_sources'):
            row[key]=sorted(set(row[key]))
        row['configured_count']=len(row['configured_sources'])
    return {'count_definition':'proveedores habilitados con ruta integrada; no son cobertura completa ni confirmación de acceso HTTP',
            'sports':output, 'inactive_excluded':['API-Sports cuando API_SPORTS_ACTIVO=0'],
            'providers_not_independent_by_default':True}
