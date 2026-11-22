---
name: skill-migrate
description: 把 Codex/Claude 技能迁到 DSH 并验证真能跑：扫描 $CODEX_HOME、openai.yaml、image_gen、个人绝对路径等死引用，能改的自动改，改不了的列清单。要"搬别人的 skill/这个技能能不能用"时用。
---

# Skill Migrate（Codex/Claude → DSH 迁移器）

DSH 只读技能开头的 `name` 和 `description`，正文和脚本里写了什么它不管。所以一个技能"能加载"和"能执行"是两件事：

- 能加载：目录里有 `SKILL.md`，文件头合规。
- 能执行：正文里让你调的每个工具、每个路径，在这台机器上真的存在。

本技能只干第二件事：把内容里的死引用找出来，能改的改掉，改不了的摊开给你选。

## 命令

```bash
P=~/.dsh/skills/skill-migrate/scripts/migrate_skill.py

python3 $P <技能目录或单个.md>                  # 体检，不写盘
python3 $P <src> --out /tmp/try --apply         # 先落临时目录看效果
python3 $P <src> --apply                        # 迁到 ~/.dsh/skills/<name>
python3 $P <src> --report PORT.md --json        # 存报告 / 机器可读
python3 $P <src> --emit-sh preflight.sh         # 生成"这台机器缺什么"的自检脚本
```

退出码：`0` 干净、`1` 有必须先解决或没有对应物的问题、`2` 源读不了。

## 依赖自检（交给用户或 agent 自己跑）

技能搬过去能加载，不代表需要的工具都在。`--emit-sh` 会从正文里抽八类东西——工具、pip/npm/brew 包、环境变量、路径、MCP 服务器、外网地址——生成 `preflight.sh`：

```bash
python3 $P <src> --emit-sh /tmp/preflight.sh && sh /tmp/preflight.sh
# ✓ python3
# ✗ pikepdf → python3 -m pip install pikepdf
# ? rea — 加 MCP 服务器 rea（需人工确认）
```

三条底线：**只查不装**（脚本里没有 install 执行）、**不改原文件**、**缺依赖不影响退出码**。缺什么、装不装，由人点头。

## 报告怎么读

| 堆 | 含义 | 你要做什么 |
|---|---|---|
| **必须先解决** | 缺 name/description、没有文件头 | 不解决就别装 |
| **建议处理（不拦人）** | description >240 字符、正文 >8 KB | 只影响每轮 token 开销，装得上 |
| **已自动改写** | `$CODEX_HOME`→`$DSH_HOME`、`~/.codex/`→`~/.dsh/`、`apply_patch`→`edit`、`the shell tool`→`bash 工具`、name 转 kebab、白名单外字段进 metadata | 复核一眼 |
| **DSH 没有对应物** | `image_gen`、`view_image`、`agents/openai.yaml`、`container.*`、`codex exec`、沙箱网络开关 | 删分支 / 换本地替代 / 标"需自备 key" |
| **建议处理** | 个人绝对路径、`TODO` 占位、`.claude/` 路径、`mcp.json`、名字字段不规范 | 有空再清 |

## 处置标准动作

- **`agents/openai.yaml`**：DSH 没有 agent 清单。删掉生成它的 import 与写入逻辑，`references/openai_yaml.md` 一起删，否则正文指向死文档。
- **`image_gen`**：DSH 无内置出图。先确认 key 在不在（`env | grep -i openai`），不在就删掉出图分支改成提示词 + 本地渲染，别留幻觉路径。
- **`view_image`**：换成 `read_image`（看图）或 `read`（看文本）。
- **个人绝对路径** `/Users/xxx/...`：改成占位符（`SAMPLE`、`TARGET_DIR`）或相对路径，否则别人装上第一句就断。
- **`codex exec` / `codex-network`**：换成 bash + 文件策略表述，改不动的明确标注不适用。
- **`pip install` / `npm install` / `npx`**：技能要联网装依赖时，正文里得写清失败怎么办；离线机器上第一步就断。
- **Claude 的 `hooks:` / `PreToolUse`**：DSH 没有插件级生命周期钩子，这段行为搬过去就是静默丢失 → 改写成技能正文里的显式步骤，或一个前置 bash 检查。
- **`.claude/agents/` / `Task(subagent_type=…)`**：Claude 的 subagent 与 DSH 的 subagent 语义不同（独立会话派发）。别照搬，按 DSH 的 `subagent` 工具重写调用点。
- **`mcp__` / `mcpServers`**：依赖 MCP 服务器。DSH 工具名是 `mcp__<server>__<tool>`，服务器没装时这些调用全不可用，正文要给出降级路径。

## 验收三步

1. `python3 ~/.dsh/skills/skill-creator/scripts/quick_validate.py <目录>` → `Skill is valid!`
2. `grep -rn "CODEX_HOME\|openai.yaml\|image_gen\|view_image" <目录>` → 只剩报告点过的行
3. 用一句真实触发句试跑，并 `ls` 正文引用的每个绝对路径

## 它查不到的东西（先看这里，别高估）

- **二进制与图片里的字符串**：只读文本文件。
- **拼接出来的工具名**：`"image" + "_gen"`、base64、变量拼接，一律漏。
- **Rust/Go/Java 里的 env 读取**：只认 Python 的 `os.environ.get` 写法。
- **Claude 的 hooks / subagents / settings.json 语义**：只报路径，不判断行为。
- **能力是否等价**：它只报告"没有 `image_gen`"，不替你决定换成哪个 CLI。
- **触发准不准**：描述压成一行只省 token，触发质量得用真实对话试。
- **网络依赖**：正文让你 `curl` 某个外网地址，它不管。

## 发现漏检怎么办

把原始技能目录（能公开的话）和这条命令的输出一起提：

```bash
python3 $P <src> --json > miss.json
env | grep -iE "codex|dsh" >> miss.json
```

漏检的典型形态是"一个新工具名"或"一种新路径写法"，加规则就是在 `RULES` 里加一行，改完跑 `python3 tests/run_tests.py`。

## 和社区插件的关系

`dsh-skillport`、`dsh-skill-adapter` 解决**发现与元数据归一化**（扫 `.claude/skills`、转 `.cursor/rules`、`when-to-use`→`whenToUse`）。它们不碰脚本里的 `$CODEX_HOME`，也不判断 `image_gen` 缺不缺 —— 那正是本技能的位置。先用它们批量导入，再用本技能逐个过一遍。
