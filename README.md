# dsh-skill-migrate

把 **Codex / Claude Code 的技能**迁进 [DeepSeek Harness（DSH）](https://github.com/deepseek-ai/deepseek-harness)，并且确认迁完**真的能跑**。

> **先说清楚定位**：这是一个补丁，不是完整方案。
> 它只覆盖我实际踩到过的坑（17 条检查），靠的是一个字符串清单，不理解语义。
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
| 一条命令跑四个回归测试，CI 里也跑 | 评估触发质量 —— 那得用真实对话试 |

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

（真实运行 `tests/fixtures/codex-sample` 的结果）

```
# migrate 报告：image-gen-legacy

## DSH 没有对应物（人工处置）
- `tool-image-gen` ×1 — Codex 内置出图工具；DSH 无对应物 → 删分支或改成需自备 key 的 CLI 调用
    - SKILL.md:9 `image_gen`
- `tool-view-image` ×1 — Codex 内置看图工具；DSH 用 read_image / read 代替
    - SKILL.md:9 `view_image`
- `openai-yaml-file` ×1 — Codex 的 agent 清单文件本身；DSH 无对应物 → 整文件删掉
    - agents/openai.yaml:1 `openai.yaml`

## 可自动改写（未写盘）
- `codex-home-var` ×1 — 环境变量改名（确认语义：home 还是配置目录）
- `codex-home-env` ×1 — Codex home 改指 DSH home

## 建议处理
- `fm-short-desc` ×1 — short-description 不在 DSH 白名单，会进 metadata
```

## 检查清单（17 条）

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
| `abs-home-path` | WARN | `/Users/xxx/`、`/home/xxx/`、`C:\Users\` —— 别人机器上不存在 |
| `fm-short-desc` / `fm-extra-keys` | WARN | 非白名单文件头字段 |
| `todo-placeholder` | WARN | `TODO` / `FIXME`，DSH 校验器会拒绝 |
| `claude-dir` / `mcp-json` | WARN | `.claude/` 路径、已被插件面板取代的 `mcp.json` |

加一条规则 = 在 `scripts/migrate_skill.py` 的 `RULES` 里加一行 `(id, 正则, 级别, 说明, 替换)`，再在 `tests/run_tests.py` 补一条断言。

## 它查不到什么（重要）

已知漏检，欢迎补充：

- **拼接构造的名字**：`"image" + "_gen"`、base64、变量拼接。
- **非 Python 的 env 读取**：`env::var("CODEX_HOME")`（Rust）、`os.Getenv`（Go）、`System.getenv`（Java）。
- **Claude 的 hooks / subagents / `settings.json` 语义**：只报路径，不判断行为。
- **网络依赖**：正文让你 `curl` 某个外网地址，它不管能不能连通。
- **触发质量**：描述压到一行只省 token，触发准不准得用真实对话试。
- **二进制与图片里的字符串**：只读文本。

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
python3 tests/run_tests.py          # 四个用例，只用标准库
pip install pyyaml && python3 tests/run_tests.py   # 有 pyyaml 的路径也测一遍
```

CI（`.github/workflows/ci.yml`）在 ubuntu + macos、Python 3.9 + 3.12 上，各跑一次"无 pyyaml"和"有 pyyaml"。

## 版本

- `0.1.0` —— 17 条检查、4 组测试、双解析器（pyyaml / 内置）

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

17 checks across three buckets: **auto-rewritten** (`CODEX_HOME` → `DSH_HOME`, tool renames, frontmatter normalization), **no DSH equivalent** (`image_gen`, `view_image`, `openai.yaml`, `codex exec`, sandbox network flags), **warnings** (personal absolute paths, TODO placeholders, `.claude/` paths). Exit code `0` clean, `1` needs attention, `2` unreadable source.

Scope disclaimer: this is a patch over the pitfalls I actually hit, implemented as a string list — it does not understand semantics, and misses concatenated names or non-Python env reads. Complements discovery/metadata tools such as `dsh-skillport` and `dsh-skill-adapter`. Unofficial, not affiliated with DeepSeek or OpenAI. MIT.
