from datetime import date
from decimal import Decimal
import re
import unicodedata

from app.numeric import number
from app.errors import DomainError

UNIT_FACTORS = {
    'v': Decimal('1'),
    'mv': Decimal('0.001'),
    'uv': Decimal('0.000001'),
    'μv': Decimal('0.000001'),
    'µv': Decimal('0.000001'),
}

BAND_PATTERN = re.compile(r'^(?P<sign>[+\-±])?\s*(?P<number>[0-9][0-9.,]*)\s*(?P<unit>[A-Za-zμµ]+)?$')


def day(text):
    try:return date.fromisoformat(text)
    except ValueError:raise DomainError('DATE','日期格式无效')


def unit_factor(unit, code='UNIT'):
    key = unicodedata.normalize('NFKC', str(unit or '')).strip().lower()
    if key not in UNIT_FACTORS:
        raise DomainError(code, '电压单位无效')
    return UNIT_FACTORS[key]


def volts(value, unit):
    return number(value) * unit_factor(unit)


def band(value, unit=''):
    """Parse a tolerance/uncertainty half-width that carries a unit.

    Accepts two-column input ("0.2" + "V") or one combined column
    ("±0.2 V").  Returns the half-width in volts, or None when the optional
    field is blank.  A band is a width, so a negative value is rejected.
    """
    text = unicodedata.normalize('NFKC', str(value if value is not None else '')).strip()
    if text in ('', '-', 'N/A', 'NULL', '未知'):
        return None
    match = BAND_PATTERN.fullmatch(text)
    if not match:
        raise DomainError('BAND', '误差带格式无效')
    if match.group('sign') == '-':
        raise DomainError('BAND', '误差带宽度不能为负')
    magnitude = number(match.group('number'))
    embedded = match.group('unit') or ''
    explicit = unicodedata.normalize('NFKC', str(unit or '')).strip()
    if embedded and explicit and unit_factor(embedded, 'BAND_UNIT') != unit_factor(explicit, 'BAND_UNIT'):
        raise DomainError('BAND_UNIT', '误差带单位冲突')
    chosen = embedded or explicit
    if not chosen:
        raise DomainError('BAND_UNIT', '误差带缺少单位')
    return magnitude * unit_factor(chosen, 'BAND_UNIT')


def range_state(value, tolerance, minimum, maximum):
    """Three-way range judgement.

    ``OUT``    reading itself is outside the closed range;
    ``EDGE``   reading is inside but the ± tolerance crosses the boundary;
    ``OK``     reading and the whole tolerance band stay inside.
    """
    inside = minimum <= value <= maximum
    if not inside:
        return 'OUT'
    if tolerance is not None and (value - tolerance < minimum or value + tolerance > maximum):
        return 'EDGE'
    return 'OK'


def range_basis(value, tolerance, minimum, maximum, state):
    """Human-readable, unit-carrying explanation of a range decision."""
    if state == 'OUT':
        return f'读数 {value} V 不在闭区间 [{minimum}, {maximum}] V 内'
    if tolerance is None:
        return f'读数 {value} V ∈ [{minimum}, {maximum}] V（未提供误差带）'
    if state == 'EDGE':
        parts = []
        if value - tolerance < minimum:
            parts.append(f'下限 {value} − {tolerance} = {value - tolerance} V < {minimum} V')
        if value + tolerance > maximum:
            parts.append(f'上限 {value} + {tolerance} = {value + tolerance} V > {maximum} V')
        return '误差带越界：' + '；'.join(parts)
    return f'读数 {value} V，误差带 ±{tolerance} V，两端均在 [{minimum}, {maximum}] V 内'


def equivalence(rows):
    parents={}
    def find(x):
        parents.setdefault(x,x)
        if parents[x]!=x:parents[x]=find(parents[x])
        return parents[x]
    for r in rows:
        a,z=find(r['device']),find(r['alias'] or r['device']);parents[max(a,z)]=min(a,z)
    return {x:find(x) for x in list(parents)}
def trace(cert,certs):
    path=[];current=cert;child=None
    while current:
        if current in path:return {'valid':False,'code':'CYCLE','path':path+[current]}
        path.append(current)
        if current not in certs:return {'valid':False,'code':'MISSING_REFERENCE','path':path}
        r=certs[current]
        if r['revoked']=='yes':return {'valid':False,'code':'REVOKED','path':path}
        if child and not day(r['valid_from'])<=day(child['valid_from'])<day(r['valid_to']):return {'valid':False,'code':'REFERENCE_EXPIRED','path':path}
        child=r;current=r['parent']
    return {'valid':True,'code':'TRACEABLE','path':path}
def descendants(start,certs):
    reached={start};todo=[start]
    while todo:
        node=todo.pop()
        for key,value in certs.items():
            if value['parent']==node and key not in reached:reached.add(key);todo.append(key)
    return sorted(reached)
