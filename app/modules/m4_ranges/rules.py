from app.domain import range_state, range_basis
from app.numeric import number


def apply(ctx):
    rows=[]
    for r in ctx['measurements']:
        tolerance=None if r.get('band_v') in (None,'') else number(r['band_v'])
        value=number(r['value_v']);minimum=number(r['min_v']);maximum=number(r['max_v'])
        state=range_state(value,tolerance,minimum,maximum)
        r['range_state']=state;r['range_valid']=state=='OK'
        basis=range_basis(value,tolerance,minimum,maximum,state);r['range_basis_text']=basis
        rows.append({'证书':r['cert'],'测量值_V':r['value_v'],'误差带_V':'' if r.get('band_v') is None else r['band_v'],'下限_V':r['min_v'],'上限_V':r['max_v'],'量程':{'OK':'符合','EDGE':'边缘待复测','OUT':'超量程'}[state],'量程依据':basis,'行号':r['行号']})
    return {'rows':rows,'metrics':[['量程符合',sum(r['range_state']=='OK' for r in ctx['measurements']),'条'],['边缘待复测',sum(r['range_state']=='EDGE' for r in ctx['measurements']),'条'],['超量程',sum(r['range_state']=='OUT' for r in ctx['measurements']),'条']]}
