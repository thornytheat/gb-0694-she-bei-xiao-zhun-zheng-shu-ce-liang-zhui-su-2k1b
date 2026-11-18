import io
import os

import pytest

from app.config import BAND_SAMPLE
from app.pipeline import calculate


@pytest.fixture
def edge_text():
    return BAND_SAMPLE.read_text(encoding='utf-8-sig')


def run_edge(client, text):
    return client.post('/api/run', json={'csv': text}).get_json()


def pending_cert(batch, cert):
    return next(item for item in batch['pending_retests'] if item['证书'] == cert)


def test_page_shows_destination_and_range_basis(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    page = client.get('/work/6?run_id=' + ident).data.decode()
    assert '量程依据' in page and '去向' in page and '待复测补交' in page
    assert 'E002' in page


def test_retest_accepts_when_band_shrinks(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    assert pending_cert(batch, 'E002')['原因码'] == 'EDGE_BAND'
    response = client.post('/api/retest', json={
        'id': ident, 'cert': 'E002', 'line': 4,
        'value': '9.995', 'error': '0.002', 'measured_at': '2026-11-17'})
    assert response.status_code == 200
    saved = response.get_json()
    row = next(r for r in saved['verdicts'] if r['证书'] == 'E002')
    assert row['结论'] == '可采用' and row['复测次数'] == 1
    assert not any(item['证书'] == 'E002' for item in saved['pending_retests'])


def test_retest_rejects_when_still_crossing(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    saved = client.post('/api/retest', json={
        'id': ident, 'cert': 'E002', 'line': 4,
        'value': '9.998', 'error': '0.01', 'measured_at': '2026-11-17'}).get_json()
    row = next(r for r in saved['verdicts'] if r['证书'] == 'E002')
    assert row['结论'] == '待复测'


def test_retest_rejects_certificate_that_expired_by_new_date(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    saved = client.post('/api/retest', json={
        'id': ident, 'cert': 'E002', 'line': 4,
        'value': '9.995', 'error': '0.002', 'measured_at': '2027-01-01'}).get_json()
    row = next(r for r in saved['verdicts'] if r['证书'] == 'E002')
    assert row['结论'] == '拒用' and 'INVALID_WINDOW' in row['原因码']


def test_retest_with_tight_band_is_accepted(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    saved = client.post('/api/retest', json={
        'id': ident, 'cert': 'E004', 'value': '5', 'error': '0.1', 'measured_at': '2026-11-17'}).get_json()
    row = next(r for r in saved['verdicts'] if r['证书'] == 'E004')
    assert row['结论'] == '可采用'


def test_duplicate_resubmission_does_not_add_decision(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    payload = {'id': ident, 'cert': 'E002', 'line': 4,
               'value': '9.995', 'error': '0.002', 'measured_at': '2026-11-17'}
    first = client.post('/api/retest', json=payload).get_json()
    second = client.post('/api/retest', json=payload).get_json()
    assert second['reused'] is True
    assert len(first['retest_rows']) == len(second['retest_rows']) == 1
    assert client.get('/api/runs/' + ident).get_json()['retest_rows'][0]['decision_id'] == first['decision_record']['decision_id']


def test_rerunning_same_batch_keeps_retest_archive(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    client.post('/api/retest', json={'id': ident, 'cert': 'E002', 'line': 4,
                                     'value': '9.995', 'error': '0.002', 'measured_at': '2026-11-17'})
    again = client.post('/api/run', json={'csv': edge_text}).get_json()
    assert again['reused'] is True and again['manifest']['run_id'] == ident
    assert len(again['retest_rows']) == 1
    assert again['verdicts'] and next(r for r in again['verdicts'] if r['证书'] == 'E002')['结论'] == '可采用'


def test_supplement_to_non_pending_record_is_rejected(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    response = client.post('/api/retest', json={'id': ident, 'cert': 'E001', 'value': '9.995',
                                                'error': '0.001', 'measured_at': '2026-11-17'})
    assert response.status_code == 422 and response.get_json()['code'] == 'NOT_PENDING'


def test_pending_record_can_be_resupplemented_until_settled(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    still = client.post('/api/retest', json={'id': ident, 'cert': 'E002', 'line': 4,
                                             'value': '9.999', 'error': '0.01',
                                             'measured_at': '2026-11-17'}).get_json()
    assert next(r for r in still['verdicts'] if r['证书'] == 'E002')['结论'] == '待复测'
    settled = client.post('/api/retest', json={'id': ident, 'cert': 'E002', 'line': 4,
                                               'value': '9.995', 'error': '0.002',
                                               'measured_at': '2026-11-17'}).get_json()
    assert next(r for r in settled['verdicts'] if r['证书'] == 'E002')['结论'] == '可采用'
    assert next(r for r in settled['verdicts'] if r['证书'] == 'E002')['复测次数'] == 2
    blocked = client.post('/api/retest', json={'id': ident, 'cert': 'E002', 'line': 4,
                                               'value': '9.996', 'error': '0.01',
                                               'measured_at': '2026-11-17'})
    assert blocked.status_code == 422 and blocked.get_json()['code'] == 'NOT_PENDING'


def test_crash_between_judge_and_commit_recovers(client, edge_text, monkeypatch):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    import app.store as store

    original = store._load
    calls = {'n': 0}

    def flaky(db, ident_arg):
        # 模拟 INSERT 之后、COMMIT 之前进程中断。
        if calls['n'] == 0:
            calls['n'] += 1
            raise RuntimeError('archive interrupted')
        return original(db, ident_arg)

    monkeypatch.setattr(store, '_load', flaky)
    payload = {'id': ident, 'cert': 'E002', 'line': 4,
               'value': '9.995', 'error': '0.002', 'measured_at': '2026-11-17'}
    with pytest.raises(RuntimeError):
        client.post('/api/retest', json=payload)
    monkeypatch.setattr(store, '_load', original)
    # 中断后事务整体回滚，没有留下半条裁决；重跑同一补交正常完成。
    assert client.get('/api/runs/' + ident).get_json()['retest_rows'] == []
    saved = client.post('/api/retest', json=payload).get_json()
    assert len(saved['retest_rows']) == 1
    assert saved['reused'] is False


def test_evidence_export_contains_review_row(client, edge_text):
    batch = run_edge(client, edge_text)
    ident = batch['manifest']['run_id']
    client.post('/api/retest', json={'id': ident, 'cert': 'E002', 'line': 4,
                                     'value': '9.995', 'error': '0.002', 'measured_at': '2026-11-17'})
    text = client.get('/api/evidence.csv?run_id=' + ident).data.decode('utf-8-sig')
    assert '复审' in text and 'EDGE_BAND' in text and 'E002' in text


def test_retest_on_unknown_batch_is_404(client):
    assert client.post('/api/retest', json={'id': 'absent', 'cert': 'X', 'value': '1',
                                            'error': '0', 'measured_at': '2026-11-17'}).status_code == 404


def test_retest_requires_run_id(client):
    response = client.post('/api/retest', json={'cert': 'X', 'value': '1'})
    assert response.status_code == 400


def test_pending_retest_has_band_from_original(client, edge_text):
    batch = run_edge(client, edge_text)
    item = pending_cert(batch, 'E004')
    assert item['误差带_V'] == '0.005' and item['测量值_V'] == '0.002'
