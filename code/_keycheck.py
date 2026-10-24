import json, collections
keys = set(); n = 0
pol = collections.Counter(); bud = collections.Counter(); qids = set()
with open('code/output/longmemeval/results.jsonl', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        n += 1
        r = json.loads(line)
        p = r.get('policy'); b = r.get('budget'); q = r.get('question_id')
        keys.add((p, b, q)); pol[p] += 1; bud[b] += 1; qids.add(q)
print('lines', n, 'unique_keys', len(keys))
print('policies', dict(pol))
print('budgets', dict(bud))
print('unique_qids', len(qids))
