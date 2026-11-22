---
name: pdf-shrink
description: 把大 PDF 压小：先装依赖，再调脚本，产物落本地。要考虑体积与清晰度的取舍时用。
---

# PDF 压缩

先装依赖：

```bash
python3 -m pip install pikepdf
brew install ghostscript
```

然后跑：

```bash
gs -sDEVICE=pdfwrite -o out.pdf in.pdf
```

工具箱在 `~/pdf工具/shrink.py`，输出目录由 `$PDF_OUT` 决定。
需要 Ghidra 时通过 MCP 调用：`mcp__rea__decompile`。
参考文档：https://example.com/pdf-guide
