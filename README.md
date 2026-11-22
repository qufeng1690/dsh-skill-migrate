# dsh-skill-migrate

[![ci](https://github.com/qufeng1690/dsh-skill-migrate/actions/workflows/ci.yml/badge.svg)](https://github.com/qufeng1690/dsh-skill-migrate/actions/workflows/ci.yml) ![python](https://img.shields.io/badge/python-3.9%20%7C%203.12-blue) ![license](https://img.shields.io/badge/license-MIT-green)

把 **Codex / Claude Code 的技能**迁进 [DeepSeek Harness（DSH）](https://github.com/deepseek-ai/deepseek-harness)，并且确认迁完**真的能跑**。

> **先说清楚定位**：这是一个补丁，不是完整方案。
> 它只覆盖我实际踩到过的坑（21 条检查），靠的是一个字符串清单，不理解语义。
> 你没踩到的坑，它多半也看不见。发现了请开 Issue —— 加一条规则就是加一行。

非官方工具，与 DeepSeek、OpenAI 无关联。

## 为什么需要

DSH 只读技能开头的 `name` 和 `description`，正文和脚本里写了什么它不管。于是"能加载"和"能执行"是两件事：

```
能加载：目录里有 SKILL.md，开头两行合规 → 出现在技能列表里
能执行：正文让你调的每个工具、每个路径，在这台机器上真的存在
```

我把 `~/.codex/skills/.system/` 里的四个技能搬过来时，实测出来的死引用是：

| 死引用 | 次数 | 后果 |
|---|---|---|
| `image_gen` | 41 | DSH 没有内置出图工具 |
| `CODEX_HOME` / `~/.codex` | 21 | 脚本指向一个不存在的目录 |
| `agents/openai.yaml` | 13 | DSH 没有 agent 清单这个概念 |
| `view_image` | 2 | 该用 `read_image` |
| `codex-network` | 4 | 沙箱网络开关，语义完全不同 |

`imagegen` 就是这样：文件头合规、目录里看得到、`skill` 也能加载 —— 但正文第一句让你调一个不存在的工具，装完等于零。

现有的搬家插件（[dsh-skillport](https://github.com/Jesse-njx/dsh-skillport)、[dsh-skill-adapter](https://github.com/zp-home/dsh-skill-adapter)）解决的是**发现与元数据归一化**：扫 `.claude/skills`、转 `.cursor/rules`、`when-to-use` → `whenToUse`、name 转 kebab。它们不碰脚本里的 `$CODEX_HOME`，也不判断 `image_gen` 缺不缺。本项目补的就是这一段。

## 能做什么 / 不能做什么

| 能 | 不能 |
|---|---|
| 找出写死的目录、环境变量、工具名，精确到文件:行号 | 理解语义 —— 凭据目录和配置目录在它眼里一样 |
| 自动改写 7 类（路径、变量、工具名、文件名、frontmatter 归一化） | 判断能力是否等价 —— 只报告"我们没 `image_gen`"，不替你选替代品 |
| 把"没有对应物"的地方列成清单，逼你做决定，不静默吞掉 | 装依赖、下载模型、跑技能里的命令 |
| 干净输入不报警（有测试保证） | 读二进制、图片里的文字，或 `"image"+"_gen"` 这种拼接 |
| 一条命令跑七组回归测试，CI 里也跑 | 评估触发质量 —— 那得用真实对话试 |

## 安装

**作为 DSH 技能**

```bash
git clone https://github.com/qufeng1690/dsh-skill-migrate.git ~/.dsh/skills/skill-migrate
```

或者把 `SKILL.md` 和 `scripts/` 放进 `~/.dsh/skills/skill-migrate/`。DSH 有目录 watch，下一轮就出现在技能列表里。技能名是 `skill-migrate`。

**作为普通命令行工具**

不需要 DSH，系统 Python 即可（有 `pyyaml` 更稳，没有则用内置极简解析器）：

```bash
python3 scripts/migrate_skill.py --help
```

## 快速开始

```bash
P=scripts/migrate_skill.py

# 体检，不写盘
python3 $P <技能目录或单个.md>

# 先落临时目录看效果
python3 $P <src> --out /tmp/try --apply

# 迁到 ~/.dsh/skills/<name>
python3 $P <src> --apply

# 存报告 / 机器可读
python3 $P <src> --report PORT.md --json
```

退出码：`0` 干净、`1` 有必须先解决或没有对应物的问题、`2` 源读不了。

## 输出长什么样

（真实运行 `tests/fixtures/codex-sample` 的结果，节选）

```
# migrate 报告：image-gen-legacy

- **A 级**：等价改写，工具直接改（`--apply` 时写盘）。判 A 的标准很窄：
  新旧工具做的是同一件事，只是名字不同。
- **B 级**：只能算近似，或者只是建议。动手前要你看一眼，改了会丢什么得你自己判断。
- **C 级**：找不到可靠替代，或者没有足够证据。原样保留，只报告，不动手。

## C 级 · DSH 没有对应物（原样保留）
- `tool-image-gen` ×1 — Codex 内置出图工具；DSH 无对应物 → 删分支或改成需自备 key 的 CLI 调用
    - SKILL.md:9 `image_gen`
- `tool-view-image` ×1 — Codex 内置看图工具；DSH 用 read_image / read 代替
    - SKILL.md:9 `view_image`
- `openai-yaml-file` ×1 — Codex 的 agent 清单文件本身；DSH 无对应物 → 整文件删掉
    - agents/openai.yaml:1 `openai.yaml`

## A 级 · 可自动改写（未写盘）
- `codex-home-var` ×1 — 环境变量改名（确认语义：home 还是配置目录）
- `codex-home-env` ×1 — Codex home 改指 DSH home

## B 级 · 建议处理（不拦人）
- `fm-short-desc` ×1 — short-description 不在 DSH 白名单，会进 metadata
```

### A/B/C 是什么意思

这三档不是新加的判断，是把原来那套 `REWRITE / WARN / UNSUPPORTED` 换成人能直接用的说法。区别在于「工具敢不敢替你动手」：

| 档 | 什么情况 | 工具怎么办 |
|---|---|---|
| **A** | 新旧工具做的是同一件事，只是名字不同（`apply_patch` → `edit`，`$CODEX_HOME` → `$DSH_HOME`） | 直接改，改完在报告里列一行记账 |
| **B** | 只能算近似，或者只是建议（description 太长、写了个人绝对路径、`.claude/` 路径） | 不改，列出来，你看了自己决定 |
| **C** | 找不到可靠替代（`image_gen`、`view_image`、`hooks:`、`container.*`） | 一个字都不动，原样保留并说明为什么 |

判 A 的标准故意收得很窄。理由是猜错的代价不对称：报一个「已知缺失」，最坏是你自己去补；把一个缺失悄悄换成个凑合的东西，就变成了「未知缺陷」——脚本能跑，产出是废的，还得多花时间才发现。

JSON 输出里每条命中都带 `tier` 字段（`A` / `B` / `C`），方便别的脚本按档过滤。

## 让别人的 agent 自己查：`--requires` / `--emit-sh`

前面的清单告诉你"哪句话会断"。这一节回答另一个问题：**这台机器到底缺什么。**

```bash
python3 scripts/migrate_skill.py <src> --emit-sh preflight.sh
sh preflight.sh          # 只检查，不安装
```

生成的脚本从正文里抽出八类东西并逐条验证：

| 类别 | 从哪来 | 检查命令 |
|---|---|---|
| 工具 | `command -v x`、代码块首词 | `command -v dotnet` |
| Python 包 | `pip install x` | `python3 -c "import x"` |
| Node 包 | `npm i x`、`npx x` | `npm ls -g x` |
| brew 包 | `brew install x` | `brew list x` |
| 环境变量 | `$DFROOT`、`${PDF_OUT}` | `test -n "${DFROOT:-}"` |
| 路径 | `~/工具箱/dfpak` | `test -e "$HOME/工具箱/dfpak"` |
| MCP 服务器 | `mcp__rea__decompile` | 人工确认（打印问号） |
| 外网地址 | 正文里的 `https://…` | `curl -sI --max-time 5` |

真实输出（`tests/fixtures/requires-sample`）：

```
✓ python3
✗ gs → 安装 gs 后重试
✗ pikepdf → python3 -m pip install pikepdf
✗ PDF_OUT → export PDF_OUT=<值>
? rea — 加 MCP 服务器 rea（需人工确认）

5 项缺失
```

三点设计取舍：

- **只查不装**：脚本里没有任何 `install` 的执行，只有 `echo` 告诉你该敲什么。装不装由人决定。
- **不改原文件**：`--requires` 是只读的，不往技能里塞字段，也不要求作者配合。
- **缺了不算失败**：依赖清单不参与退出码，`rc` 仍然只反映"能不能迁移"。

这条正好接在 `dsh-skill-mover` 之后：搬过来的技能，agent 一条命令就知道缺什么，再问你要不要装。

## 检查清单（21 条 + 1 条软提醒）

表里的「级别」就是报告里 A/B/C 的来源：`REWRITE` → A，`WARN` → B，`UNSUPPORTED` → C。

| rule | 级别 | 说明 |
|---|---|---|
| `codex-home-env` | REWRITE | `os.environ.get("CODEX_HOME", "~/.codex")` → `DSH_HOME` / `~/.dsh` |
| `codex-home-var` | REWRITE | `$CODEX_HOME`、`${CODEX_HOME}` → `$DSH_HOME` |
| `codex-dir` | REWRITE | `~/.codex/`、`.codex/` → `~/.dsh/` |
| `tool-apply-patch` | REWRITE | Codex 补丁工具 → DSH 的 `edit` |
| `tool-shell` | REWRITE | `the shell tool` → `bash 工具` |
| `fm-name-kebab` | REWRITE | 名字转小写连字符（`Image Gen Legacy` → `image-gen-legacy`） |
| `fm-extra→metadata` | REWRITE | 白名单外字段（`short-description`、`when-to-use`、`version`…）塞进 `metadata` |
| `openai-yaml` / `openai-yaml-file` | UNSUPPORTED | Codex 的 agent 清单文件，DSH 无对应物 |
| `tool-image-gen` | UNSUPPORTED | 内置出图工具 |
| `tool-view-image` | UNSUPPORTED | 内置看图工具 |
| `tool-container` | UNSUPPORTED | `container.open/exec/write_stdin` |
| `codex-exec` | UNSUPPORTED | 依赖 `codex` CLI 的调用链 |
| `codex-network` | UNSUPPORTED | Codex 沙箱网络开关 |
| `runtime-net-install` | WARN | `pip install` / `npm install` / `npx` —— 运行时要联网装依赖，离线就断 |
| `mcp-server-ref` | WARN | `mcp__` / `mcpServers` —— 依赖 MCP 服务器，没装时调用不可用 |
| `claude-hooks` | UNSUPPORTED | Claude Code 的 `hooks:` / `PreToolUse` 等生命周期钩子 —— DSH 没有插件级 hooks，这段行为会被静默丢掉 |
| `claude-subagent` | UNSUPPORTED | `.claude/agents/`、`Task(subagent_type=…)` —— DSH 的 subagent 是独立会话派发，语义不同 |
| `abs-home-path` | WARN | `/Users/xxx/`、`/home/xxx/`、`C:\Users\` —— 别人机器上不存在 |
| `fm-desc-long` | 软提醒 | description >240 字符 —— **不影响加载**，只影响每轮固定 token 开销 |
| `fm-short-desc` / `fm-extra-keys` | WARN | 非白名单文件头字段 |
| `todo-placeholder` | WARN | `TODO` / `FIXME`，DSH 校验器会拒绝 |
| `claude-dir` / `mcp-json` | WARN | `.claude/` 路径、已被插件面板取代的 `mcp.json` |

加一条规则 = 在 `scripts/migrate_skill.py` 的 `RULES` 里加一行 `(id, 正则, 级别, 说明, 替换)`，再在 `tests/run_tests.py` 补一条断言。

## 语料回归：79 个真实技能

规则不是拍脑袋加的。拿三个公开仓库的 79 个技能当语料逐个读文本检查过一遍 —— 只读文件，不调用模型，也不安装任何东西：

| 来源 | 技能数 |
|---|---|
| `openai/skills`（`.system` + `.curated`） | 59 |
| `anthropics/skills` | 19 |
| `obra/superpowers` | 1 |

这一轮改了两件事：

1. **description >240 从「阻塞」降级为「软提醒」**。之前 79 个里有 **40 个**只因描述长被判「必须先解决」，而描述长只是 token 开销，根本不影响能不能装。退出码 1 的技能数从 60 降到 44。
2. **补两条规则**：`runtime-net-install`（386 处，技能要联网装依赖）与 `mcp-server-ref`（35 处，依赖 MCP 服务器）。

顺带一个发现：市面上最接近本项目的，是 OpenAI 自己仓库里的 `migrate-to-codex` 技能 —— 方向正好相反（Claude Code → Codex），做的是**指令文件、agent、MCP 配置的整体搬家**，不做工具名与路径的可执行性检查。两边互补，不冲突。

想自己复现（克隆到临时目录，别放进 `~/.dsh/skills`，否则会被当成技能注入目录、白烧 token）：

```bash
mkdir -p /tmp/skill-corpus && cd /tmp/skill-corpus
git clone --depth 1 https://github.com/openai/skills.git openai-skills
git clone --depth 1 https://github.com/anthropics/skills.git anthropic-skills
for d in */; do find "$d" -name SKILL.md | sed 's|/SKILL.md||' ; done \
  | while read d; do python3 scripts/migrate_skill.py "$d" --json; done
```

## 它不做什么（这是设计，不是遗漏）

有人看完之后列过一串不足。大部分是对的，但其中一半是**主动不做**——因为做了会比不做更糟。下面把话说清楚，你就能判断这个工具配不配你的场景：

| 你可能期待 | 它实际的行为 | 为什么不那样做 |
|---|---|---|
| 读懂代码语义，判断这段逻辑还能不能跑 | 只做正则匹配，按 `文件:行号` 报位置 | 语义分析要编译器或模型，成本高且会误判；宁可漏报，不乱报 |
| 永远认得所有平台的新工具 | 21 条规则，写在代码里，明写着会漏 | 未知工具名的正确出口是 Issue 模板，不是猜 |
| 发现工具不存在，顺手挑个最佳替代品 | 只说「DSH 没有 `image_gen`」，不指定换哪个 | 换成什么取决于你有没有 key、离不离线；猜错比不换更贵 |
| 自动把缺的依赖装上 | 只数出 `pip install` / `npm install` 的行数和位置 | 改环境该由人决定，而且装依赖本身会引入网络失败 |
| 测一下正文里的网址通不通 | 不联网，一个请求都不发 | 同一技能在墙内墙外结论不同；静态结论更稳，要测你自己 `curl` |
| 保证技能会被正确触发 | 只保证描述合规、不超长 | 触发是运行时行为，只能真跑；静态判断不了 |
| 把 Claude 的 hooks 和 subagents 一起搬过来 | 检出并标成 **DSH 没有对应物**，等人决策 | 语义完全不同，静默搬过去等于行为丢失 —— 这条正是 v0.3.0 补的 |
| 保证迁移后行为 100% 一致 | 只保证「没有指向不存在东西的死引用」 | 死引用可判定，行为等价不可判定 |

换句话说：**它管的是"会不会第一步就断"，不管"效果好不好"。**

### 仍然会漏的情形

- **拼接构造的名字**：`"image" + "_gen"`、base64、变量拼接。
- **非 Python 的 env 读取**：`env::var("CODEX_HOME")`（Rust）、`os.Getenv`（Go）、`System.getenv`（Java）。
- **二进制与图片里的字符串**：只读文本。
- **Claude `settings.json` 的实际语义**：只报路径，不判断它会做什么。

如果你踩到了清单外的坑，用这个命令把现场打出来，连同原始技能目录（能公开的话）一起提 Issue：

```bash
python3 scripts/migrate_skill.py <src> --json > miss.json
env | grep -iE "codex|dsh" >> miss.json
```

## 和另外几个工具怎么搭

```
远端仓库 ──skill-installer──▶ ~/.dsh/skills ──本项目──▶ 能真正跑的技能
              (搬运)                        (内容体检 + 改写)

.claude/、.cursor/ ──dsh-skillport / dsh-skill-adapter──▶ 同一个目录
                        (发现 + 元数据归一化)
```

三个可以一起用：先批量导入，再逐个过一遍 `migrate_skill.py`。

## 开发

```bash
python3 tests/run_tests.py          # 七个用例，只用标准库
pip install pyyaml && python3 tests/run_tests.py   # 有 pyyaml 的路径也测一遍
```

CI（`.github/workflows/ci.yml`）在 ubuntu + macos、Python 3.9 + 3.12 上，各跑一次"无 pyyaml"和"有 pyyaml"。

## 版本

- `0.1.0` —— 17 条检查、5 组测试、双解析器（pyyaml / 内置）
- `0.2.0` —— 19 条检查 + 1 条软提醒、5 组测试；description 超长不再阻塞（79 个真实技能回归后修正）
- `0.3.0` —— 21 条检查、6 组测试；新增 `claude-hooks` / `claude-subagent`（Claude 高级工作流不再被静默丢掉），README 增「它不做什么」
- `0.4.0` —— 新增 `--requires` / `--emit-sh`：从正文抽八类依赖，生成只查不装的 `preflight.sh`；7 组测试
- `0.5.0` —— 报告按 A/B/C 三档分段并解释含义，JSON 每条命中带 `tier`；8 组测试
- `0.5.1` —— 修依赖抽取的两处误报：正文英文 `which restores` 被当成命令、XML 命名空间被当外网依赖；9 组测试

## License

MIT。见 [LICENSE](LICENSE)。非官方工具，与 DeepSeek、OpenAI 无关联。

---

## English

`dsh-skill-migrate` ports Codex / Claude Code skills into DeepSeek Harness **and checks they still work**. DSH only reads `name` + `description`, so hard-coded `$CODEX_HOME` paths, `agents/openai.yaml` generators and `image_gen` calls survive a naive copy and break at step one.

```bash
python3 scripts/migrate_skill.py <skill-dir>            # report only
python3 scripts/migrate_skill.py <skill-dir> --apply    # rewrite + install to ~/.dsh/skills
python3 tests/run_tests.py                              # stdlib only
```

21 checks (+1 soft warning) across three buckets: **auto-rewritten** (`CODEX_HOME` → `DSH_HOME`, tool renames, frontmatter normalization), **no DSH equivalent** (`image_gen`, `view_image`, `openai.yaml`, `codex exec`, sandbox network flags), **warnings** (personal absolute paths, TODO placeholders, `.claude/` paths). Exit code `0` clean, `1` needs attention, `2` unreadable source.

Scope disclaimer: this is a patch over the pitfalls I actually hit, implemented as a string list — it does not understand semantics, and misses concatenated names or non-Python env reads. Complements discovery/metadata tools such as `dsh-skillport` and `dsh-skill-adapter`. Unofficial, not affiliated with DeepSeek or OpenAI. MIT.
