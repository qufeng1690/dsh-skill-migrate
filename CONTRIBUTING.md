# 贡献指南

最短路径：**你踩到一个坑 → 我加一条规则 → 你跑一遍测试**。整套东西的价值就在于"坑的清单"够长，代码本身很短。

## 报漏检（不用会写代码）

开 Issue 时选「漏检报告」模板，附上两样东西：

1. 那个技能的目录（能公开就传，不能就贴相关的几行）
2. 这条命令的输出：

```bash
python3 scripts/migrate_skill.py <技能目录> --json
```

## 加一条规则

改一个地方：`scripts/migrate_skill.py` 里的 `RULES`。

```python
("tool-xxx", r"\bxxx\b", "UNSUPPORTED", "一句话说明后果和替代方案", None),
```

字段顺序：`(id, 正则, 级别, 说明, 替换文本)`。

| 级别 | 什么时候用 |
|---|---|
| `REWRITE` | DSH 有确定的对应物，能安全替换。必须给第 5 个参数。 |
| `UNSUPPORTED` | DSH 没有对应物，必须人工决策。**不要**为了消警硬替换成别的东西。 |
| `WARN` | 建议处理，但不该拦人。 |

三条底线：

- **别静默吞掉**：没有对应物的东西一律 `UNSUPPORTED`，让人自己选删还是换。
- **说明写后果**："DSH 没有内置出图" 比 "unsupported tool" 有用。
- **正则别太宽**：`\bimage_gen\b` 而不是 `image`，误报会让人直接不用这个工具。

## 加一个测试

改 `tests/run_tests.py`，或往 `tests/fixtures/` 加一个最小样本（一个 `SKILL.md` + 必要时两三个文件）。规矩：

- 每个 fixture 只演示一件事，别堆成真实技能。
- 断言写成 `check("中文说明", 条件, 失败时给的信息)`。
- 新规则必须有一条"能检出"的断言；涉及 `REWRITE` 的还要断言改写后的文本长什么样。

```bash
python3 tests/run_tests.py                          # 无 pyyaml 路径
PYTHONPATH=/tmp/noyaml python3 tests/run_tests.py   # 有/无两条路径都要绿
```

## 提交前

- [ ] `python3 tests/run_tests.py` 全绿
- [ ] 有 pyyaml 和没 pyyaml 两种情况都跑过
- [ ] 报告里的中文能直接看懂，不堆术语
- [ ] 没把别人的技能内容整段抄进 fixture

## 不做什么

- **不猜能力等价**：不会自动把 `image_gen` 换成某个具体 CLI —— 那需要人来定。
- **不删文件**：`agents/openai.yaml` 只点名，删不删用户决定。
- **不做插件**：本项目是技能 + 一个脚本，能塞进任何有 Python 的机器。批量发现交给 `dsh-skillport` / `dsh-skill-adapter`。
