---
name: clean-sample
description: 一份本来就合规的技能，用来确认移植器不会对干净输入报假警
metadata:
  origin: fixture
---

# Clean Sample

把 `input.csv` 读成表格，统计每列空值数量，输出 `report.md`。

## 步骤

1. `python3 scripts/stat.py input.csv`
2. 检查 `report.md` 里空值最多的三列
