import importlib
mods = ['tiktoken', 'rank_bm25', 'openai', 'matplotlib', 'numpy', 'yaml', 'pytest']
for m in mods:
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, '__version__', '?')
        print('OK   %s %s' % (m, v))
    except Exception as e:
        print('FAIL %s: %s: %s' % (m, type(e).__name__, e))
