# legacy_120q — frozen 120-question (mimo-v2.6-flash) tables

These files are the **previous table generation**: 21 cells x n=120 = 2,520 records,
answerer mimo-v2.6-flash, sourced from `output/results.jsonl`.

They are **not inputs of the shipped paper**. `output/final/paper.tex` gets every
main-grid table from `../tables500/` (deepseek-v4.1-flash, 500 questions, 25 cells,
12,500 records across `results.jsonl` + `results_r8.jsonl` + `results_r9.jsonl`).

Moved here on 2026-11-07 because same-named files existed in both `tables/` and
`tables500/` (main, headline, latency, stats, bytype, consolidated_emrel,
reader_comparison), which made it easy to publish the wrong generation by copying
the wrong directory.

`tables/` itself is NOT legacy: six of its files are still \input by paper.tex as
frozen ablation artifacts (fc_archive_absolutes, ablation_summary_len,
ablation_allocation, ablation_retrieval, plug_baselines, judge_type).
