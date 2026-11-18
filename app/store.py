import sqlite3, json, os
from pathlib import Path
from app.errors import DomainError
from app.retest import enrich

def connection():
    path=Path(os.environ.get('APP_DB','data/runs.sqlite3'));path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    # 补交裁决只追加不覆盖；decision_id 由补交内容确定性生成，重跑同一补交不会新增。
    db.execute('CREATE TABLE IF NOT EXISTS retests(decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)')
    return db

def _load(db, ident):
    row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
    if row is None: raise DomainError('NOT_FOUND','批次不存在',404)
    result={**json.loads(row['payload']),'revision':row['revision'],'decision':row['decision']}
    result['retests']=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM retests WHERE run_id=? ORDER BY rowid',(ident,))]
    return result

def save(result):
    with connection() as db:
        ident=result['manifest']['run_id'];row=db.execute('SELECT payload,revision,decision FROM runs WHERE id=?',(ident,)).fetchone()
        if row:
            return {**enrich(_load(db,ident)),'reused':True}
        db.execute('INSERT INTO runs(id,payload) VALUES (?,?)',(ident,json.dumps(result,ensure_ascii=False)))
        stored=_load(db,ident)
    return {**enrich(stored),'reused':False}

def get_run(ident):
    with connection() as db: return enrich(_load(db,ident))

def latest():
    with connection() as db:
        row=db.execute('SELECT id FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
        return enrich(_load(db,row['id'])) if row else None

def history():
    with connection() as db: return [dict(r) for r in db.execute('SELECT id,revision,decision FROM runs ORDER BY rowid DESC')]

def review(ident, revision, decision):
    if decision not in ('通过','退回'): raise DomainError('DECISION','复核动作无效')
    with connection() as db:
        changed=db.execute('UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?',(decision,ident,revision)).rowcount
        if not changed: raise DomainError('VERSION','版本已变化，请重新载入',409)
    return {'revision':revision+1,'decision':decision}

def append_retest(ident, record):
    """Persist one retest decision atomically and return (batch, newly_added).

    A crash before COMMIT leaves no trace; retrying the same supplement hits the
    deterministic primary key and only re-reads the existing row.
    """
    with connection() as db:
        inserted=db.execute('INSERT OR IGNORE INTO retests(decision_id,run_id,payload,created_at) VALUES (?,?,?,?)',
                   (record['decision_id'],ident,json.dumps(record,ensure_ascii=False),record['created_at'])).rowcount
        batch=_load(db,ident)
    return enrich(batch), bool(inserted)
