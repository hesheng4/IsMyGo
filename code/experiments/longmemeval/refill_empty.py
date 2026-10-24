# -*- coding: utf-8 -*-
"""stage3 补全: 重跑 fresh 代全部空预测记录 (26 pt0 + 338 空文本)。

机制完全复用 e0_cleanup.py (仓库既有清洗脚本) 的原地替换 + 事前备份模式,
差异仅在目标集合: pred 为空即重跑 (含 full_context, 依 leader 2026-10-15 19:32 裁决
"无空 pred" 与 A1 更新)。历史备份 (results_failed_backup.jsonl 等) 已随 2026-10-16
复现收尾清理移除, 最终结果以 results.jsonl (2,520 条, 零空预测) 为准。
用法: python refill_empty.py [--dry]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ISMYGO_ROOT", str(Path(__file__).resolve().parents[3]))) / "code"
sys.path.insert(0, str(ROOT / 'experiments' / 'longmemeval'))

from common import format_context, load_questions  # noqa: E402
from llm import answer_with_memory  # noqa: E402
from policies import build_memory  # noqa: E402
from score import em, relaxed_em, token_f1  # noqa: E402

OUT = ROOT / 'output' / 'longmemeval'
CACHE = OUT / 'cache'
RP = OUT / 'results.jsonl'
BAK_INVALID = OUT / 'results_invalid_backup2.jsonl'
BAK_FULL = OUT / 'results.jsonl.bak-pre-refill'


def load_summaries(max_words: int) -> dict[str, str]:
    sums: dict[str, str] = {}
    sf = CACHE / 'summaries'
    if not sf.is_dir():
        return sums
    for f in sf.glob('*.json'):
        d = json.loads(f.read_text(encoding='utf-8'))
        if d.get('max_words', 60) == max_words:
            sums[d['session_id']] = d['text']
    return sums


def answer_cache_file(cache_key: str) -> Path:
    h = hashlib.sha1(f'answer:v2:{cache_key}'.encode('utf-8')).hexdigest()[:16]
    return CACHE / 'answers' / f'{h}.json'


async def main() -> None:
    dry = '--dry' in sys.argv
    questions = {q.question_id: q for q in load_questions()}
    lines = RP.read_text(encoding='utf-8').splitlines()
    records = [json.loads(l) for l in lines if l.strip()]
    print(f'[refill] results.jsonl 总记录 {len(records)}')

    # 目标: fresh 代 (model=mimo) + 120 样本 + pred 为空 (含 pt0 与空文本)
    targets = []
    for i, r in enumerate(records):
        if r.get('model') != 'mimo-v2.6-flash':
            continue
        if '@' in str(r['policy']):
            continue
        if r['question_id'] not in questions:
            continue
        # 目标: 空预测 或 prompt_tokens==0 (e0 规则: 客户端失败/拒答记账缺失均重跑)
        if (not str(r.get('pred', '')).strip()
                or r.get('prompt_tokens', 0) == 0):
            targets.append((i, r))

    by_pol = Counter(f"{r['policy']}@{r['budget']}" for _, r in targets)
    pt0 = sum(1 for _, r in targets if r.get('prompt_tokens', 0) == 0)
    print(f'[refill] 空预测目标 {len(targets)} 条 (pt0={pt0}, 空文本={len(targets)-pt0})')
    for k in sorted(by_pol):
        print(f'      {k}: {by_pol[k]}')

    cached = [1 for _, r in targets if answer_cache_file(
        f"{r['policy']}|{r['budget']}|{r['question_id']}").exists()]
    print(f'[refill] 目标键已有答案缓存文件: {len(cached)} (空文本者将删除后重调)')

    if dry:
        print('[refill] --dry: 只报告')
        return
    if not targets:
        print('[refill] 无需补全')
        return

    sums60 = load_summaries(60)
    print(f'[refill] 摘要缓存 w60 条数: {len(sums60)}')

    t0 = time.time()
    sem = asyncio.Semaphore(8)
    replaced: dict[int, dict] = {}
    failed: list[str] = []
    empty_again: list[str] = []

    async def rerun(i: int, r: dict) -> None:
        pol_field = r['policy']
        q = questions[r['question_id']]
        budget = r['budget']
        key = f'{pol_field}|{budget}|{q.question_id}'
        sums = {}
        if pol_field == 'compression' or pol_field.startswith('hierarchical'):
            sums = sums60
        plan = build_memory(pol_field, q, budget, sums)
        cp = answer_cache_file(key)
        if cp.exists():
            d = json.loads(cp.read_text(encoding='utf-8'))
            if not d.get('text', '').strip():
                cp.unlink()
        async with sem:
            try:
                ans = await answer_with_memory(
                    q.question, q.question_date,
                    format_context(plan.segments), CACHE / 'answers', key)
            except Exception as e:  # noqa: BLE001
                failed.append(key)
                print(f'[refill FAIL] {key}: {type(e).__name__}: {str(e)[:60]}',
                      flush=True)
                return
        if not ans['text'].strip():
            empty_again.append(key)
        replaced[i] = {
            'policy': pol_field, 'budget': budget, 'question_id': q.question_id,
            'question_type': q.question_type, 'gold': q.answer,
            'pred': ans['text'],
            'em': em(ans['text'], q.answer),
            'relaxed_em': relaxed_em(ans['text'], q.answer),
            'f1': token_f1(ans['text'], q.answer),
            'memory_footprint_tokens': plan.footprint_tokens,
            'n_turns': plan.n_turns, 'n_summaries': plan.n_summaries,
            'access_ms': round(plan.access_ms, 4),
            'e2e_ms': round(ans.get('ms', 0.0), 2),
            'prompt_tokens': ans.get('prompt_tokens', 0),
            'completion_tokens': ans.get('completion_tokens', 0),
            'model': 'mimo-v2.6-flash',
        }
        print(f'[refill ok] {key} pred={ans["text"][:30]!r}', flush=True)

    await asyncio.gather(*(rerun(i, r) for i, r in targets))

    # 事前备份: 无效记录子集 + 全文件
    if not dry:
        BAK_INVALID.write_text(
            '\n'.join(json.dumps(r, ensure_ascii=False) for _, r in targets) + '\n',
            encoding='utf-8')
        BAK_FULL.write_text(RP.read_text(encoding='utf-8'), encoding='utf-8')
        for i, new_rec in replaced.items():
            records[i] = new_rec
        with RP.open('w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'[refill] 替换 {len(replaced)}/{len(targets)} 条; '
              f'备份 -> {BAK_INVALID.name} (+ 全量 {BAK_FULL.name})')

    print(f'[refill] 耗时 {time.time()-t0:.0f}s; 异常失败 {len(failed)} 条 '
          f'(保留原空记录); 重跑后仍为空文本 {len(empty_again)} 条')
    if failed:
        print('FAILED_KEYS:', json.dumps(failed, ensure_ascii=False))
    if empty_again:
        print('EMPTY_AGAIN_KEYS:', json.dumps(empty_again, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
