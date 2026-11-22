---
name: noise-sample
description: 回归样本：正文里的英文句子不该被当成命令，XML 命名空间不该被当成外网依赖。
---

# 噪声样本

解压时用 zipfile，而不是 `unzip`，which restores symlinks —— 从外部拿到的 docx 一律按不可信处理。

同理，which reads the file、which the tool points at，这些都不是命令。

转换时要写这些命名空间，它们只是标识符，不是拿来访问的地址：
`http://schemas.openxmlformats.org/wordprocessingml/2006/main`，
`http://openoffice.org/2000/script`。

真命令长这样：

```bash
python3 scripts/build.py --out doc.docx
```

安装：

```bash
pip install python-docx
```
