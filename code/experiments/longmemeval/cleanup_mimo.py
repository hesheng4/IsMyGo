# -*- coding: utf-8 -*-
"""清理: 只留 mimo-v2.6-flash 命名空间。
1) results.jsonl 备份(时间戳) + 删除 model != mimo 记录;
2) cache/{answers,summaries,fetch} 中非 mimo 命名空间缓存删除;
3) GLM 跨读者旧表 robustness_m47/m51/m53/model.tex 删除(两处 tables/)。
用法: python cleanup_mimo.py [--dry]
"""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("ISMYGO_ROOT", str(Path(__file__).resolve().parents[3])))
OUT = ROOT / 'code' / 'output' / 'longmemeval'
RP = OUT / 'results.jsonl'
CACHE = OUT / 'cache'
MIMO = 'mimo-v2.6-flash'
dry = '--dry' in sys.argv

# ---- 1) results.jsonl ----
lines = [l for l in RP.read_text(encoding='utf-8').splitlines() if l.strip()]
recs = [json.loads(l) for l in lines]
keep = [r for r in recs if r.get('model') == MIMO]
drop = [r for r in recs if r.get('model') != MIMO]
print(f'[clean] results.jsonl: {len(recs)} -> keep {len(keep)}, drop {len(drop)}')
print('[clean] drop model breakdown:',
      dict(Counter(str(r.get('model')) for r in drop)))
if not dry:
    ts = time.strftime('%Y%m%d-%H%M%S')
    bak = OUT / f'results.jsonl.bak-cleanup-mimo-{ts}'
    bak.write_text(RP.read_text(encoding='utf-8'), encoding='utf-8')
    with RP.open('w', encoding='utf-8') as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'[clean] 已写 {len(keep)} 行, 备份 -> {bak.name}')

# ---- 2) cache 命名空间清理 ----
for sub in ('answers', 'summaries', 'fetch'):
    d = CACHE / sub
    if not d.is_dir():
        print(f'[clean] cache/{sub}: 目录不存在, 跳过')
        continue
    files = list(d.glob('*.json'))
    ns = Counter()
    del_n = 0
    for p in files:
        try:
            obj = json.loads(p.read_text(encoding='utf-8'))
            m = obj.get('model') or obj.get('answer_model') or ''
        except (OSError, ValueError):
            m = '<corrupt>'
        tag = m if m else '<legacy-no-model>'
        ns[tag] += 1
        if m != MIMO:
            del_n += 1
            if not dry:
                p.unlink()
    print(f'[clean] cache/{sub}: 共 {len(files)} 文件, 命名空间 {dict(ns)},'
          f' 删除 {del_n}' + (' (dry)' if dry else ''))

# ---- 3) GLM 跨读者旧表 ----
OLD_T = {'robustness_m47.tex', 'robustness_m51.tex', 'robustness_m53.tex',
         'robustness_model.tex'}
for tdir in (OUT / 'tables', ROOT / 'output' / 'tables'):
    if not tdir.is_dir():
        print(f'[clean] {tdir}: 目录不存在, 跳过')
        continue
    for name in sorted(OLD_T):
        p = tdir / name
        if p.exists():
            if not dry:
                p.unlink()
            print(f'[clean] 删除旧表 {p.relative_to(ROOT)}' + (' (dry)' if dry else ''))
print('[clean] done')
