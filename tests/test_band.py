from decimal import Decimal

import pytest

from app.domain import band, range_state
from app.errors import DomainError
from app.pipeline import calculate
from app.config import BAND_SAMPLE


@pytest.fixture
def edge():
    return calculate(BAND_SAMPLE.read_text(encoding='utf-8-sig'))


def verdict(result, cert):
    return next(r for r in result['verdicts'] if r['证书'] == cert)


def test_band_with_embedded_unit():
    assert band('±0.2 V') == Decimal('0.2')
    assert band('0.5mV') == Decimal('0.0005')


def test_band_unit_conflict_rejected():
    with pytest.raises(DomainError):
        band('0.2 V', 'mV')


def test_band_requires_unit():
    with pytest.raises(DomainError):
        band('0.2')


def test_band_negative_width_rejected():
    with pytest.raises(DomainError):
        band('-0.2 V')


def test_three_way_state():
    assert range_state(Decimal('5'), Decimal('0.001'), Decimal('0'), Decimal('10')) == 'OK'
    assert range_state(Decimal('9.995'), Decimal('0.01'), Decimal('0'), Decimal('10')) == 'EDGE'
    assert range_state(Decimal('10'), Decimal('0'), Decimal('0'), Decimal('10')) == 'OK'
    assert range_state(Decimal('11'), Decimal('0.1'), Decimal('0'), Decimal('10')) == 'OUT'
    assert range_state(Decimal('5'), None, Decimal('0'), Decimal('10')) == 'OK'


def test_edge_case_sample_has_all_three_destinations(edge):
    assert verdict(edge, 'E001')['结论'] == '可采用'
    assert verdict(edge, 'E002')['结论'] == '待复测'
    assert verdict(edge, 'E002')['原因码'] == 'EDGE_BAND'
    assert verdict(edge, 'E004')['结论'] == '待复测'
    assert verdict(edge, 'E003')['结论'] == '拒用'
    assert verdict(edge, 'E003')['原因码'] == 'OUT_OF_RANGE'


def test_reading_inside_but_band_outside_is_retest(edge):
    # 9.995 在闭区间内，但 ±0.01 的上端点越界；只看读数会误收。
    assert verdict(edge, 'E002')['量程依据'].startswith('误差带越界')
    assert verdict(edge, 'E002')['去向'].startswith('待复测')


def test_band_inside_is_accepted(edge):
    assert verdict(edge, 'E001')['量程依据'].count('两端均在') == 1


def test_expired_certificate_still_rejected_despite_band(edge):
    row = verdict(edge, 'E006')
    assert row['结论'] == '拒用' and row['原因码'] == 'INVALID_WINDOW'


def test_revoked_certificate_still_rejected_despite_band(edge):
    row = verdict(edge, 'E007')
    assert row['结论'] == '拒用' and row['原因码'] == 'REVOKED'


def test_broken_trace_still_rejected_despite_band(edge):
    assert verdict(edge, 'E011')['结论'] == '拒用'
    assert verdict(edge, 'E011')['原因码'] == 'MISSING_REFERENCE'


def test_no_band_keeps_binary_judgement(edge):
    row = verdict(edge, 'E009')
    assert row['结论'] == '可采用' and '未提供误差带' in row['量程依据']


def test_millivolt_band_normalized(edge):
    assert verdict(edge, 'E010')['误差带_V'] == '0.010'


def test_sample_without_band_still_partitions_binary():
    result = calculate()
    assert not any(r['结论'] == '待复测' for r in result['verdicts'])


def test_bad_band_is_quarantined(raw):
    header = ','.join(raw.splitlines()[0].split(',') + ['error', 'error_unit'])
    body = 'X1,DX1,坏带仪器,ROOT,2026-01-01,2027-01-01,0,10,V,no,2026-11-17,5,V,1,0.2,\n'
    result = calculate(header + '\n' + body)
    assert any(q['原因码'] == 'BAND_UNIT' for q in result['quarantine'])


def test_duplicate_optional_header_rejected():
    header = 'cert,device,alias,parent,valid_from,valid_to,minimum,maximum,unit,revoked,measured_at,value,measure_unit,version,error,error_unit,error\n'
    with pytest.raises(DomainError):
        calculate(header)


def test_unknown_column_rejected():
    header = 'cert,device,alias,parent,valid_from,valid_to,minimum,maximum,unit,revoked,measured_at,value,measure_unit,version,nonsense\n'
    with pytest.raises(DomainError):
        calculate(header)


def test_mixed_combined_and_split_band_columns_rejected():
    header = 'cert,device,alias,parent,valid_from,valid_to,minimum,maximum,unit,revoked,measured_at,value,measure_unit,version,error,error_unit,band\n'
    with pytest.raises(DomainError):
        calculate(header)


def test_conflicting_band_for_same_certificate_isolated(raw):
    header = ','.join(raw.splitlines()[0].split(',') + ['error', 'error_unit'])
    first = 'B1,DB1,带宽仪器,ROOT,2026-01-01,2027-01-01,0,10,V,no,2026-11-17,5,V,1,0.001,V\n'
    second = 'B1,DB1,带宽仪器,ROOT,2026-01-01,2027-01-01,0,10,V,no,2026-11-17,5,V,1,0.01,V\n'
    result = calculate(header + '\n' + first + second)
    assert any(q['原因码'] == 'CONFLICT' for q in result['quarantine'])
    assert result['certs']['B1']['conflicted'] is True
