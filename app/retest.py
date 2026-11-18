"""补交读数、误差带与测量日后的重判。

设计要点：
- 原批次载荷不可变；重判结果以“复议裁决”追加存档，按批次查询时叠加显示。
- 每条裁决的 ID 由批次、记录、读数、误差带、测量日确定性生成，因此同一份补交
  重跑（包括存档写入中途失败后重试）只会命中同一行，不会新增裁决。
- 写入在单个事务内完成：中断时整体回滚，重试即可恢复。
"""
import hashlib
import time
from decimal import Decimal

from app.domain import band, day, range_basis, range_state, volts
from app.errors import DomainError
from app.numeric import number

CONCLUSION_ACCEPT = '可采用'
CONCLUSION_REJECT = '拒用'
CONCLUSION_RETEST = '待复测'

DESTINATIONS = {
    CONCLUSION_ACCEPT: '可采用，已计入可用测量',
    CONCLUSION_REJECT: '拒用，不得作为有效测量',
    CONCLUSION_RETEST: '待复测，需补交读数与误差带',
}


def canonical(value, places='0.0000001'):
    return str(Decimal(value).quantize(Decimal(places)).normalize())


def decision_id(run_id, cert, line, value_v, band_v, measured_at):
    payload = '|'.join([run_id, str(cert), str(line), canonical(value_v), '' if band_v is None else canonical(band_v), measured_at])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]


def _pick(spec, *names):
    for name in names:
        if name in spec and spec[name] is not None:
            return spec[name]
    return None


def _line_of(spec):
    value = _pick(spec, 'line', '行号', 'record_line')
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DomainError('LINE', '原始行号必须为整数')


def _supplement_band(spec):
    combined = _pick(spec, 'band', 'error_band', 'band_v', '误差带')
    # 页面与接口都按伏特展示和接收；显式提供单位时以显式单位为准。
    unit = _pick(spec, 'error_unit', 'band_unit', 'uncertainty_unit', '误差单位') or 'V'
    if combined not in (None, ''):
        return band(combined, unit)
    raw = _pick(spec, 'error', 'uncertainty', 'tolerance', '误差', '不确定度', '允差')
    if raw is None or str(raw).strip() in ('', '-', 'N/A', 'NULL', '未知'):
        # 补交必须同时给出读数、误差带与测量日；缺失时不能静默沿用旧误差带。
        raise DomainError('MISSING', '补交误差带不能为空')
    return band(raw, unit)


def _supplement_value(spec):
    raw = _pick(spec, 'value', 'reading', '读数', 'value_v')
    if raw in (None, ''):
        raise DomainError('MISSING', '补交读数不能为空')
    # 读数默认按伏特解释（与原记录规范化后的 value_v 一致）；可显式覆盖单位。
    unit = _pick(spec, 'value_unit', 'measure_unit', '读数单位') or 'V'
    return volts(raw, unit)


def rejudge(run, spec):
    """Rejudge one pending measurement with a supplemented reading."""
    if not isinstance(spec, dict):
        raise DomainError('REQUEST', '补交记录必须为对象', 400)
    cert = _pick(spec, 'cert', '证书', '证书编号')
    if not cert:
        raise DomainError('MISSING', '补交记录缺少证书号')
    line = _line_of(spec)
    measurements = run.get('measurements') or []
    candidates = [m for m in measurements if m.get('cert') == cert]
    if line is not None:
        candidates = [m for m in candidates if int(m.get('行号', -1)) == line]
    if not candidates:
        raise DomainError('NOT_FOUND', '批次中找不到该待复测记录', 404)
    if len(candidates) > 1:
        raise DomainError('AMBIGUOUS', '同一证书存在多条记录，请同时提供原始行号')
    measurement = candidates[0]
    line = int(measurement['行号'])

    value_v = _supplement_value(spec)
    measured_at = _pick(spec, 'measured_at', '测量日', 'measured')
    if measured_at in (None, ''):
        raise DomainError('MISSING', '补交测量日不能为空')
    measured_at = str(day(str(measured_at)))
    band_v = _supplement_band(spec)

    ident = decision_id(run['manifest']['run_id'], cert, line, value_v, band_v, measured_at)

    # 同一份补交已经裁决过：直接复用，不再新增。
    existing = {d['decision_id']: d for d in (run.get('retests') or [])}
    if ident in existing:
        return existing[ident], True

    # 只有仍处于待复测的记录可补交：原始结论为待复测，且此前重判未得出可采用/拒用。
    latest = latest_decision(run, cert, line)
    current = latest or base_verdict(run, cert, line)
    if current is None:
        raise DomainError('NOT_FOUND', '批次中找不到该待复测记录', 404)
    if current['结论'] != CONCLUSION_RETEST:
        raise DomainError('NOT_PENDING', '该记录已有可采用或拒用结论，不能再次补交')

    cert_record = (run.get('certs') or {}).get(cert)
    if cert_record is None:
        raise DomainError('NOT_FOUND', '批次中找不到该证书', 404)

    start, end = day(cert_record['valid_from']), day(cert_record['valid_to'])
    measured_day = day(measured_at)
    overlaps = []
    for key, other in (run.get('certs') or {}).items():
        if key == cert:
            continue
        if other.get('canonical') == cert_record.get('canonical') and max(day(other['valid_from']), start) < min(day(other['valid_to']), end):
            overlaps.append(key)
    window_valid = start <= measured_day < end and not cert_record.get('conflicted') and not overlaps

    chain = (run.get('chains') or {}).get(cert)
    chain_valid = bool(chain and chain.get('valid'))
    chain_code = (chain or {}).get('code') or 'MISSING_REFERENCE'

    state = range_state(value_v, band_v, number(cert_record['min_v']), number(cert_record['max_v']))
    basis = range_basis(value_v, band_v, number(cert_record['min_v']), number(cert_record['max_v']), state)

    reasons = []
    if not window_valid:
        reasons.append('INVALID_WINDOW')
    if state == 'OUT':
        reasons.append('OUT_OF_RANGE')
    elif state == 'EDGE':
        reasons.append('EDGE_BAND')
    if not chain_valid:
        reasons.append(chain_code)
    blocking = [r for r in reasons if r != 'EDGE_BAND']
    if blocking:
        conclusion = CONCLUSION_REJECT
    elif 'EDGE_BAND' in reasons:
        conclusion = CONCLUSION_RETEST
    else:
        conclusion = CONCLUSION_ACCEPT

    record = {
        'decision_id': ident,
        'run_id': run['manifest']['run_id'],
        '证书': cert,
        '行号': line,
        '测量日': measured_at,
        '读数_V': str(value_v),
        '误差带_V': None if band_v is None else str(band_v),
        '量程依据': basis,
        '结论': conclusion,
        '原因码': ','.join(reasons) or 'ACCEPT',
        '去向': DESTINATIONS[conclusion],
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    return record, False


def base_verdict(run, cert, line):
    for row in run.get('original_verdicts') or run.get('verdicts') or []:
        if row.get('证书') == cert and int(row.get('行号', -1)) == int(line):
            return row
    return None


def latest_decision(run, cert, line):
    latest = None
    for decision in run.get('retests') or []:
        if decision.get('证书') == cert and int(decision.get('行号', -1)) == int(line):
            latest = decision
    return latest


def enrich(run):
    """Overlay the append-only retest archive onto a stored batch for display."""
    retests = run.get('retests') or []
    # 幂等：已叠加过的批次以 original_verdicts 为原始层，避免重复叠加。
    original = list(run.get('original_verdicts') or run.get('verdicts') or [])
    by_record = {}
    for decision in retests:
        key = (decision.get('证书'), int(decision.get('行号', -1)))
        by_record.setdefault(key, []).append(decision)

    effective = []
    pending = []
    for row in original:
        key = (row.get('证书'), int(row.get('行号', -1)))
        history = by_record.get(key, [])
        latest = history[-1] if history else None
        conclusion = latest['结论'] if latest else row.get('结论', '')
        reasons = latest['原因码'] if latest else row.get('原因码', '')
        row_basis = (latest or {}).get('量程依据') or row.get('量程依据') or ''
        item = {
            **row,
            '结论': conclusion,
            '原因码': reasons,
            '原始结论': row.get('结论', ''),
            '原始原因码': row.get('原因码', ''),
            '量程依据': row_basis,
            '复测次数': len(history),
            '去向': DESTINATIONS.get(conclusion, conclusion),
        }
        effective.append(item)
        if conclusion == CONCLUSION_RETEST:
            measurement = next((m for m in run.get('measurements') or [] if m.get('cert') == key[0] and int(m.get('行号', -1)) == key[1]), None) or {}
            pending.append({
                '证书': key[0],
                '行号': key[1],
                '设备': row.get('设备', ''),
                '测量值_V': (history[-1]['读数_V'] if history else row.get('测量值_V', '')),
                '误差带_V': (history[-1]['误差带_V'] if history else measurement.get('band_v')),
                '测量日': (history[-1]['测量日'] if history else row.get('测量日', '')),
                '原因码': reasons,
            })

    run['original_verdicts'] = original
    run['verdicts'] = effective
    run['pending_retests'] = pending
    run['retest_rows'] = retests

    stage = (run.get('stages') or {}).get('6')
    if stage is not None:
        stage['rows'] = effective
        stage['metrics'] = [
            ['可采用', sum(r['结论'] == CONCLUSION_ACCEPT for r in effective), '条'],
            ['拒用', sum(r['结论'] == CONCLUSION_REJECT for r in effective), '条'],
            ['待复测', sum(r['结论'] == CONCLUSION_RETEST for r in effective), '条'],
            ['行数守恒', '相符' if run.get('balanced') else '差异', ''],
        ]
        stage['retests'] = retests
    return run
