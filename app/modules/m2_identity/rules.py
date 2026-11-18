from app.domain import day, equivalence, volts, band
from app.numeric import number
from app.errors import DomainError
from app.reasons import isolate


def row_band(r, columns):
    """Resolve the optional error-band from either a combined or split column."""
    combined = columns.get('combined')
    value_column = columns.get('value')
    unit_column = columns.get('unit')
    if combined and r.get(combined, '') not in ('',):
        # 一列写法优先；若同时给了单位列，band() 会校验一致性。
        return band(r.get(combined), r.get(unit_column, '') if unit_column else '')
    if value_column:
        text = r.get(value_column, '')
        if text not in ('',):
            return band(text, r.get(unit_column, '') if unit_column else '')
    return None


def apply(ctx):
    certs={};measurements=[];seen=set();duplicates=0;conflicted=set()
    fields=('device','parent','valid_from','valid_to','minimum','maximum','unit','revoked','version','band_v')
    columns=ctx.get('band_columns') or {}
    for r in ctx['rows']:
        try:
            if not r['cert'] or not r['device']:raise DomainError('MISSING','证书或设备为空')
            start,end=day(r['valid_from']),day(r['valid_to']);day(r['measured_at']);value=volts(r['value'],r['measure_unit']);minimum=volts(r['minimum'],r['unit']);maximum=volts(r['maximum'],r['unit'])
            tolerance=row_band(r,columns)
            if start>=end or minimum>maximum:raise DomainError('RANGE','证书区间无效')
            if r['revoked'] not in ('yes','no'):raise DomainError('REVOKED_FLAG','撤销标识无效')
            if r['version']!='1':raise DomainError('VERSION','不支持的证书版本')
            item={**r,'value_v':str(value),'min_v':str(minimum),'max_v':str(maximum),'band_v':None if tolerance is None else str(tolerance)}
            # 允许后出现相同业务键的相同内容（重复行），但同证书的读数/误差带定义必须一致。
            if r['cert'] in certs and any(certs[r['cert']].get(k)!=item.get(k) for k in fields):
                conflicted.add(r['cert'])
                isolate(ctx,r,'CONFLICT','同证书定义冲突')
                continue
            key=(r['cert'],r['measured_at'],r['value'],r['measure_unit'],item['band_v'])
            if key in seen:duplicates+=1;continue
            seen.add(key);certs[r['cert']]=item;measurements.append(item)
        except DomainError as e:isolate(ctx,r,e.code,e.message)
    # A conflicted certificate is never trusted for either retained or later measurements.
    for cert in conflicted:certs[cert]['conflicted']=True
    names=equivalence([r for r in measurements if r['cert'] not in conflicted])
    for r in measurements: r['canonical']=names.get(r['device'],r['device'])
    ctx.update(certs=certs,measurements=measurements,duplicates=duplicates)
    return {'rows':[{'证书':r['cert'],'设备':r['canonical'],'别名':r['alias'],'父证书':r['parent'],'定义状态':'冲突' if r['cert'] in conflicted else '一致','行号':r['行号']} for r in measurements],'metrics':[['证书',len(certs),'份'],['冲突定义',len(conflicted),'份'],['重复',duplicates,'条']]}
