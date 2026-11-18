import csv, io
from app.config import HEADERS, LIMIT
from app.errors import DomainError
from app.reasons import isolate
from app.config import BAND_VALUE_HEADERS, BAND_UNIT_HEADERS, BAND_COMBINED_HEADERS

OPTIONAL = set(BAND_VALUE_HEADERS + BAND_UNIT_HEADERS + BAND_COMBINED_HEADERS)

def decode(raw):
    for encoding in ('utf-8-sig','gb18030'):
        try: return raw.decode(encoding)
        except UnicodeDecodeError: pass
    raise DomainError('ENCODING','无法识别文件编码')


def band_columns(head):
    """Locate the optional error-band columns by header alias.

    Returns {'value': name|None, 'unit': name|None, 'combined': name|None}.
    Only one alias per role is allowed; combined and split写法的混用会被拒绝，
    避免两份误差带谁生效说不清。
    """
    present = set(head)
    def pick(candidates, role):
        found = [name for name in candidates if name in present]
        if len(found) > 1:
            raise DomainError('HEADER', f'误差带{role}列重复')
        return found[0] if found else None
    columns = {
        'value': pick(BAND_VALUE_HEADERS, '数值'),
        'unit': pick(BAND_UNIT_HEADERS, '单位'),
        'combined': pick(BAND_COMBINED_HEADERS, '整列'),
    }
    if columns['combined'] and (columns['value'] or columns['unit']):
        raise DomainError('HEADER', '误差带不要混用整列与分列写法')
    return columns


def read_rows(ctx):
    text=ctx['text'].lstrip('﻿')
    if not text: raise DomainError('EMPTY','输入为空')
    reader=csv.reader(io.StringIO(text, newline=''), strict=True)
    try: head=next(reader,None)
    except csv.Error: raise DomainError('STRUCTURE','表头损坏')
    if head is None: raise DomainError('BLANK','文件仅有空行')
    head=[x.strip() for x in head]
    # 必填列必须齐全且不重复；额外的误差带列只允许出现一次。
    if len(set(head))!=len(head) or not set(HEADERS).issubset(set(head)):
        raise DomainError('HEADER','字段缺失或重复')
    if any(name not in HEADERS and name not in OPTIONAL for name in head):
        raise DomainError('HEADER','字段缺失或重复')
    ctx['band_columns']=band_columns(head)
    rows=[];ctx['input_count']=0;ctx['blank_count']=0;ctx['header_count']=0
    try:
        for cells in reader:
            if len(rows)+len(ctx['quarantine']) >= LIMIT: raise DomainError('LIMIT','文件超过一万行')
            if not cells or all(not x.strip() for x in cells): ctx['blank_count']+=1;continue
            if cells==head: ctx['header_count']+=1;continue
            ctx['input_count']+=1
            if len(cells)!=len(head):
                isolate(ctx,{'行号':reader.line_num,'原值':'|'.join(cells)},'COLUMNS','列数不符');continue
            rows.append({**dict(zip(head,[x.strip() for x in cells])), '行号':reader.line_num})
    except csv.Error: raise DomainError('STRUCTURE','引号未闭合或记录截断')
    if not rows and not ctx['quarantine']: raise DomainError('HEADER_ONLY' if not ctx['blank_count'] else 'BLANK','文件没有业务记录')
    ctx['rows']=rows
    return rows
