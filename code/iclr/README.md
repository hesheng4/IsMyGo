# code/iclr — 旧论文目录（不要在这里改论文）

本目录**不是**当前论文源。当前定稿源是 `output/final/paper.tex`
（The Memory Trilemma Under a Fixed Token Budget，deepseek-v4.1-flash，500 题 / 25 格 / 12,500 条），
构建产物 `output/final/paper.pdf`（18 页），打包副本 `paper/paper.pdf`。

## legacy_2026-10-16/ 是什么

2026-10-16 那一代英文稿：标题 *Memory Strategy Trade-offs Under a Fixed Token Budget:
An Empirical Study on LongMemEval-S*，数据口径为 mimo-v2.6-flash 120 题 / 21 格 / **2,520 条**
（`output/results.jsonl`）。它已被 2026-10-24 起的 500 题重写版取代，保留原因只有一个：
`code/tests/test_system.py::test_reviewer_language_agnostic_iclr_tex` 用它做「评测器对英文
ICLR 稿判分是否与中文 Markdown 稿同尺度」的回归样本。

## 规则

- 论文数字与排版一律改 `output/final/paper.tex`；
- 本目录 `iclr2025_conference.{sty,bst}` 仍是模板文件，`output/final/` 下亦有同名副本；
- 若要让回归测试改测当前定稿，请把该测试的 `TEX` 指向 `output/final/paper.tex`，
  并同时把 `RESULTS` 换成 500 题主网格（`code/output/longmemeval/results.jsonl`），
  否则数字溯源断言会因代际不匹配而失败。
