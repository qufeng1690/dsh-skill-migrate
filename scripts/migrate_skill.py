#!/usr/bin/env python3
"""migrate_skill.py — 把 Codex / Claude Code 生态的 skill 迁移成 DSH 能真正跑的样子。

做的事：
  1. 解析 frontmatter，按 DSH 白名单归一化（多余键塞 metadata，name 转 kebab）
  2. 全目录扫描 Codex / Claude 专有标记，按 REWRITE / UNSUPPORTED / WARN 分级
  3. REWRITE 类直接替换（--apply 时写盘），UNSUPPORTED 类列出人工处置点
  4. 产出 PORT.md 报告，可选跑 quick_validate 复核

用法：
  python3 migrate_skill.py SRC                     # 只体检，不写盘
  python3 migrate_skill.py SRC --out DIR --apply    # 移植并写盘
  python3 migrate_skill.py SRC --json               # 机器可读
  python3 migrate_skill.py SRC --report PORT.md
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".py", ".sh", ".bash", ".zsh", ".js", ".mjs",
    ".cjs", ".ts", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".rb",
    ".pl", ".ps1", ".bat", ".html", ".css", ".svg", ".xml",
}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".DS_Store"}

DSH_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}
DESC_SOFT_LIMIT = 240       # 目录每轮固定开销，超了就该压
BODY_SOFT_LIMIT = 8000      # 正文超过这个体量，说明该拆 references/

# (id, regex, severity, note, replacement)
# severity: REWRITE 可自动替换 / UNSUPPORTED 必须人工处置 / WARN 建议处理

# A/B/C 分级：把"规则后果"翻译成别人看得懂的三档
# A = 有把握等价，工具直接改；B = 只能算近似，动手前要人点头；C = 没证据，别碰，列出来
TIER = {
    "REWRITE": ("A", "等价改写，已自动完成"),
    "WARN": ("B", "近似或建议，需要你确认"),
    "UNSUPPORTED": ("C", "没法确认，原样保留"),
}
TIER_LEGEND = [
    "- **A 级**：等价改写，工具直接改（`--apply` 时写盘）。判 A 的标准很窄：新旧工具做的是同一件事，只是名字不同。",
    "- **B 级**：只能算近似，或者只是建议。动手前要你看一眼，改了会丢什么得你自己判断。",
    "- **C 级**：找不到可靠替代，或者没有足够证据。原样保留，只报告，不动手。",
]
RULES = [
    ("codex-home-env",
     r'os\.environ\.get\(\s*["\']CODEX_HOME["\']\s*,\s*os\.path\.expanduser\(\s*["\']~/?\.codex["\']\s*\)\s*\)',
     "REWRITE",
     "Codex home 改指 DSH home",
     'os.environ.get("DSH_HOME", os.path.expanduser("~/.dsh"))'),
    ("codex-home-var", r'\$CODEX_HOME|\$\{CODEX_HOME\}', "REWRITE",
     "环境变量改名（确认语义：home 还是配置目录）", "$DSH_HOME"),
    ("codex-dir", r'~/?\.codex/|(?<![\w.])\.codex/', "REWRITE",
     "路径指向 ~/.dsh（注意 ~/.codex/auth.json 这类凭据文件 DSH 不读）", "~/.dsh/"),
    ("openai-yaml", r'agents/openai\.yaml|openai\.yaml', "UNSUPPORTED",
     "Codex 专有的 agent 清单；DSH 不存在，生成代码整块删掉，别只改字符串", None),
    ("tool-image-gen", r'\bimage_gen\b', "UNSUPPORTED",
     "Codex 内置出图工具；DSH 无对应物 → 删分支或改成需自备 key 的 CLI 调用", None),
    ("tool-view-image", r'\bview_image\b', "UNSUPPORTED",
     "Codex 内置看图工具；DSH 用 read_image / read 代替", None),
    ("tool-apply-patch", r'\bapply_patch\b', "REWRITE",
     "Codex 的补丁工具 → DSH 的 edit / write", "edit"),
    ("tool-shell", r'\b(?:the\s+)?shell\s+tool\b', "REWRITE",
     "Codex 的 shell 工具 → DSH 的 bash 工具", "bash 工具"),
    ("tool-container", r'\bcontainer\.(?:open|exec|write_stdin)\b', "UNSUPPORTED",
     "Codex 容器工具；DSH 无对应物", None),
    ("codex-exec", r'\bcodex\s+exec\b', "UNSUPPORTED",
     "依赖 codex CLI 的调用链；本机没有 codex 可执行", None),
    ("codex-network", r'codex-network|network_proxy|networkAccess', "UNSUPPORTED",
     "Codex 沙箱网络开关；DSH 用 file policy / 审批策略表达", None),
    ("claude-hooks", r'(?m)^hooks\s*:|PreToolUse|PostToolUse|UserPromptSubmit|SessionStart|SessionEnd|SubagentStop', "UNSUPPORTED",
     "Claude Code 的 hooks 生命周期钩子；DSH 没有插件级 hooks，这段行为会被静默丢掉 → 改写成技能内显式步骤或 bash 前置检查", None),
    ("claude-subagent", r'Task\s*\(\s*subagent_type|~?/?\.claude/agents/|"subagents?"\s*:|subagent_type', "UNSUPPORTED",
     "Claude 的 subagent 定义/调用；DSH 的 subagent 是独立会话派发，语义不同 → 人工改写，别直接搬", None),
    ("fm-short-desc", r'(?m)^short-description\s*:', "WARN",
     "short-description 不在 DSH 白名单，会进 metadata", None),
    ("fm-extra-keys", r'(?m)^(title|version|applies_to|requires|intent|when-to-use|when_to_use)\s*:', "WARN",
     "非白名单 frontmatter 键 → 塞 metadata 或挪正文", None),
    ("abs-home-path", r'/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|[A-Za-z]:\\Users\\', "WARN",
     "个人电脑的绝对路径；别人机器上没有这个目录，改成占位符或相对路径", None),
    ("runtime-net-install", r'(?m)^\s*(?:python3?\s+-m\s+)?pip3?\s+install|^\s*npm\s+(?:install|i)\b|\bnpx\s+\w', "WARN",
     "运行时要联网装依赖；离线或没权限的机器上第一步就断，正文里应写清失败怎么办", None),
    ("mcp-server-ref", r'mcp__|mcpServers|"mcpServers"', "WARN",
     "依赖 MCP 服务器；DSH 的工具是 mcp__<server>__<tool>，服务器没装时这些调用全不可用", None),
    ("todo-placeholder", r'TODO|\[TODO[^\]]*\]|FIXME', "WARN",
     "校验器会因未完成的 TODO 占位报错", None),
    ("claude-dir", r'~?/?\.claude/|CLAUDE\.md', "WARN",
     "Claude Code 的路径/文件名；确认 DSH 侧是否有对应物", None),
    ("mcp-json", r'~/?\.dsh/mcp\.json|~/?\.codex/mcp\.json', "WARN",
     "MCP 配置已改由插件面板写 cordis.patch.yml，mcp.json 不再被读取", None),
]

KEY_ORDER = ["name", "description", "license", "allowed-tools", "metadata"]


def log(msg, quiet=False):
    if not quiet:
        print(msg, file=sys.stderr)


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def parse_frontmatter(text):
    """返回 (fm_dict, body, had_frontmatter)。"""
    if not text.startswith("---"):
        return {}, text, False
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text, False
    raw, body = m.group(1), text[m.end():]
    data = {}
    if yaml is not None:
        try:
            loaded = yaml.safe_load(raw)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    if not data:  # 手写最小解析器，容忍缺 pyyaml
        for line in raw.splitlines():
            mm = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.+?)\s*$", line)
            if mm and not line.startswith((" ", "\t")):
                data[mm.group(1)] = mm.group(2).strip("\"'")
    return data, body, True


def kebab(name):
    s = re.sub(r"[^0-9A-Za-z]+", "-", str(name)).strip("-").lower()
    return re.sub(r"-{2,}", "-", s) or "unnamed-skill"


def iter_text_files(root):
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXT or fn in {"SKILL.md", "README.md"}:
                yield os.path.join(dirpath, fn)


def scan(root):
    hits = []
    for path in iter_text_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        if os.path.basename(path) == "openai.yaml":
            hits.append({
                "rule": "openai-yaml-file", "severity": "UNSUPPORTED", "tier": "C", "file": path,
                "line": 1, "match": os.path.basename(path),
                "note": "Codex 的 agent 清单文件本身；DSH 无对应物 → 整文件删掉",
            })
        for rid, pat, sev, note, repl in RULES:
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append({
                    "rule": rid, "severity": sev, "tier": TIER[sev][0], "file": path, "line": line,
                    "match": m.group(0)[:80], "note": note,
                })
    return hits


def rewrite_text(text, applied):
    for rid, pat, sev, note, repl in RULES:
        if sev != "REWRITE" or repl is None:
            continue
        new, n = re.subn(pat, repl.replace("\\", "\\\\"), text)
        if n:
            applied.append({"rule": rid, "count": n, "file": None})
            text = new
    return text


def normalize_frontmatter(fm, applied):
    fixed = dict(fm)
    problems = []
    if not fixed.get("name"):
        problems.append("缺 name")
    if not fixed.get("description"):
        problems.append("缺 description")
    if fixed.get("name") and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(fixed["name"])):
        old = fixed["name"]
        fixed["name"] = kebab(old)
        applied.append({"rule": "fm-name-kebab", "count": 1, "file": f"name: {old} → {fixed['name']}"})
    if fixed.get("description"):
        desc = re.sub(r"\s+", " ", str(fixed["description"])).strip()
        fixed["description"] = desc
    extra = {k: v for k, v in fixed.items() if k not in DSH_KEYS}
    if extra:
        meta = fixed.get("metadata") if isinstance(fixed.get("metadata"), dict) else {}
        for k, v in extra.items():
            meta.setdefault(kebab(k), v)
        fixed["metadata"] = meta
        for k in extra:
            fixed.pop(k, None)
        applied.append({"rule": "fm-extra→metadata", "count": len(extra), "file": ", ".join(sorted(extra))})
    out = {k: fixed[k] for k in KEY_ORDER if k in fixed} | {k: v for k, v in fixed.items() if k not in KEY_ORDER}
    return out, problems


def desc_warnings(fm):
    """description 超长只是每轮固定开销，不影响加载 —— 不该拦人。"""
    desc = re.sub(r"\s+", " ", str(fm.get("description") or "")).strip()
    if len(desc) > DESC_SOFT_LIMIT:
        return [f"`fm-desc-long` — description {len(desc)} 字符，超过 {DESC_SOFT_LIMIT} 软上限；"
                f"不影响加载，只影响每轮固定 token 开销"]
    return []


def _emit_scalar(v):
    """没有 pyyaml 时的最小 YAML 标量输出：只在必要时加引号。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    needs_quote = (
        s == ""
        or s != s.strip()
        or "\n" in s
        or any(ch in s for ch in ":#")
        or s[0] in "-?[]{}&*!|>'\"%@`,"
    )
    return json.dumps(s, ensure_ascii=False) if needs_quote else s


def dump_frontmatter(fm):
    if yaml is not None:
        body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    else:
        lines = []
        for k, v in fm.items():
            if isinstance(v, dict):
                lines.append(f"{k}:")
                lines += [f"  {kk}: {_emit_scalar(vv)}" for kk, vv in v.items()]
            else:
                lines.append(f"{k}: {_emit_scalar(v)}")
        body = "\n".join(lines)
    return f"---\n{body}\n---\n"


IGNORE_BINS = {
    "cd", "echo", "export", "source", "sudo", "then", "fi", "if", "for", "do", "done",
    "else", "elif", "while", "case", "esac", "exit", "return", "set", "unset", "read",
    "cat", "ls", "cp", "mv", "rm", "mkdir", "chmod", "chown", "touch", "grep", "sed",
    "awk", "find", "head", "tail", "sort", "uniq", "wc", "cut", "tr", "xargs", "tee",
    "git", "curl", "wget", "open", "which", "command", "test", "kill", "ps", "sleep",
    "python", "node", "sh", "bash", "zsh", "env", "make", "npm", "npx", "pip", "pip3",
}
IGNORE_ENV = {"PATH", "HOME", "PWD", "SHELL", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "TERM"}
URL_RE = re.compile(r'https?://[^\s)"\'`<>]+')
CODE_FENCE = re.compile(r'(?ms)^```[^\n]*\n(.*?)^```')
# XML 命名空间、许可证链接这类"不是给人访问的地址"，别塞进 preflight 去 curl
NS_URL_HOSTS = (
    "schemas.openxmlformats.org", "schemas.microsoft.com", "openxmlformats.org",
    "www.w3.org", "purl.org", "ns.adobe.com", "json-schema.org",
    "www.apache.org/licenses", "creativecommons.org/licenses",
    "openoffice.org", "oasis-open.org", "xmlns.com",
)


def _is_noise_url(url):
    low = url.lower()
    return any(h in low for h in NS_URL_HOSTS) or low.endswith((".xsd", ".dtd", ".rng"))


def _fence_commands(blob):
    """只从围栏代码块里认命令。正文明文里的 "reads - ..." 不是命令。"""
    cmds = []
    for block in CODE_FENCE.finditer(blob):
        for raw in block.group(1).splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = re.sub(r'^\$\s*', '', line)
            line = re.sub(r'^(?:sudo|env)\s+', '', line)
            m = re.match(r'([a-z][a-z0-9_.\-]{1,20})(.*)$', line)
            if not m:
                continue
            word, rest = m.group(1), m.group(2)
            if not rest.strip():          # 光一个词，不像命令
                continue
            if not rest.startswith(" "):
                continue
            if not re.match(r"""\s+(-{1,2}[A-Za-z]|["'$./~]|\S+/)""", rest):
                continue
            cmds.append(word)
    return cmds


def _uniq(items):
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _path_check(path):
    expanded = "$HOME" + path[1:] if path.startswith("~") else path
    return f'test -e "{expanded}"'


def collect_requires(root):
    """从技能正文里抽出"这台机器得先有什么"，只读，不执行、不联网。"""
    texts = []
    for path in iter_text_files(root):
        try:
            text = read_text(path)
        except OSError:
            continue
        texts.append((path, text))
    blob = "\n".join(t for _, t in texts)

    pips = re.findall(r'(?:python3?\s+-m\s+)?pip3?\s+install\s+(?:-[A-Za-z-]+\s+)*([A-Za-z0-9_.\-]+)', blob)
    npms = re.findall(r'npm\s+(?:install|i)\s+(?:-g\s+)?(@?[A-Za-z0-9_./\-]+)', blob)
    npxs = re.findall(r'npx\s+(@?[A-Za-z0-9_./\-]+)', blob)
    brews = re.findall(r'brew\s+install\s+(?:--cask\s+)?([A-Za-z0-9@/.\-]+)', blob)
    # 只认 `command -v x` / `which x` 出现在代码块或反引号里的；正文里 "which restores" 是散文
    checked = re.findall(r'(?m)(?:^\s*\$\s*|`)\s*(?:command\s+-v|which)\s+([A-Za-z0-9_.\-]+)', blob)
    fences = _fence_commands(blob)
    envs = re.findall(r'\$\{?([A-Z][A-Z0-9_]{2,})\}?', blob)
    paths = re.findall(r'(?:~/[^\s"\'`)|<>,;]+|/var/[^\s"\'`)|<>,;]+|/Users/[^\s"\'`)|<>,;]+)', blob)
    mcps = re.findall(r'mcp__([A-Za-z0-9_]+)__', blob)
    urls = [u for u in URL_RE.findall(blob) if not _is_noise_url(u)]

    tools = _uniq([t for t in checked + fences if t not in IGNORE_BINS])
    return {
        "tools": [{"name": t, "check": f"command -v {t}", "hint": f"安装 {t} 后重试"}
                  for t in tools],
        "python": [{"name": p_, "check": f'python3 -c "import {p_.replace("-", "_")}"',
                    "hint": f"python3 -m pip install {p_}"} for p_ in _uniq(pips)],
        "node": [{"name": n, "check": f"npm ls -g {n.split('/')[0]}",
                  "hint": f"npm i -g {n}"} for n in _uniq(npms + npxs)],
        "brew": [{"name": b, "check": f"brew list {b}", "hint": f"brew install {b}"}
                 for b in _uniq(brews)],
        "env": [{"name": e, "check": f'test -n "${{{e}:-}}"', "hint": f"export {e}=<值>"}
                for e in _uniq([e for e in envs if e not in IGNORE_ENV])],
        "paths": [{"name": p_, "check": _path_check(p_), "hint": "放到位或改技能里的路径"}
                  for p_ in _uniq(paths)],
        "mcp": [{"name": m, "check": "(在 DSH 设置→MCP Servers 里看)", "hint": f"加 MCP 服务器 {m}"}
                for m in _uniq(mcps)],
        "urls": [{"name": u, "check": f"curl -sI --max-time 5 {u} >/dev/null", "hint": "确认能联网访问"}
                 for u in _uniq(urls)][:20],
    }


def render_requires(req):
    groups = [("工具", "tools"), ("Python 包", "python"), ("Node 包", "node"),
              ("brew 包", "brew"), ("环境变量", "env"), ("路径", "paths"),
              ("MCP 服务器", "mcp"), ("外网地址", "urls")]
    total = sum(len(req.get(k) or []) for _, k in groups)
    if not total:
        return []
    lines = ["", "## 这台机器需要先具备（交给 agent 自查，不自动安装）"]
    for label, key in groups:
        items = req.get(key) or []
        if not items:
            continue
        lines.append("")
        lines.append(f"**{label}**")
        for it in items:
            lines.append(f"- [ ] `{it['name']}` — 检查：`{it['check']}` — 缺了：{it['hint']}")
    lines += ["", "想让 agent 一条命令查完：`migrate_skill.py <src> --emit-sh preflight.sh && sh preflight.sh`"]
    return lines


def emit_preflight(req, name, path):
    lines = ["#!/bin/sh", f"# preflight for {name}", "# 只检查，不安装。缺什么由人决定要不要装。", "fail=0"]
    for _, key in (("工具", "tools"), ("Python 包", "python"), ("Node 包", "node"),
                   ("brew 包", "brew"), ("环境变量", "env"), ("路径", "paths"),
                   ("MCP 服务器", "mcp"), ("外网地址", "urls")):
        for it in req.get(key) or []:
            desc = it["name"].replace('"', "'")
            chk = it["check"].replace('"', '\"')
            hint = it["hint"].replace('"', "'")
            if key == "mcp":
                lines.append(f'echo "? {desc} — {hint}（需人工确认）"')
                continue
            suffix = "" if ">/dev/null" in chk else " >/dev/null 2>&1"
            lines.append(f'if {chk}{suffix}; then echo "✓ {desc}"; '
                         f'else echo "✗ {desc} → {hint}"; fail=$((fail+1)); fi')
    lines += ['echo', 'if [ "$fail" -eq 0 ]; then echo "全部就绪"; else echo "$fail 项缺失"; fi', 'exit "$fail"', '']
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    os.chmod(path, 0o755)


def port(src, out, apply_changes, quiet=False):
    src_is_dir = os.path.isdir(src)
    skill_md = os.path.join(src, "SKILL.md") if src_is_dir else src
    if not os.path.isfile(skill_md):
        log(f"[x] 找不到 SKILL.md: {skill_md}", quiet)
        return None
    text = read_text(skill_md)
    fm, body, had_fm = parse_frontmatter(text)
    if not had_fm:
        log("[!] 没有 frontmatter，DSH 不会收录", quiet)

    _, problems = normalize_frontmatter(fm, []) if fm else ([], [])
    hits = scan(src)
    applied_rewrites = []
    for h in hits:
        if h["severity"] == "REWRITE":
            applied_rewrites.append(h)

    report = {
        "source": os.path.abspath(src),
        "name": (kebab(fm["name"]) if fm.get("name") else (os.path.basename(src) if src_is_dir else "unknown")),
        "frontmatter_before": dict(fm),
        "frontmatter_after": None,
        "problems": problems,
        "warnings": desc_warnings(fm),
        "hits": hits,
        "requires": collect_requires(src),
        "applied": [],
        "out": None,
    }

    if not apply_changes:
        return report

    fm_norm, problems = normalize_frontmatter(fm, report["applied"])
    report["frontmatter_after"] = fm_norm

    target = os.path.join(out, str(fm_norm.get("name") or os.path.basename(src)))
    if os.path.abspath(target) == os.path.abspath(src):
        log("[x] 源目录就是目标目录，换 --out", quiet)
        return report
    if os.path.exists(target):
        shutil.rmtree(target)
    if src_is_dir:
        shutil.copytree(src, target, ignore=shutil.ignore_patterns(*SKIP_DIRS))
    else:
        os.makedirs(target, exist_ok=True)
        shutil.copy2(src, os.path.join(target, "SKILL.md"))

    for path in iter_text_files(target):
        try:
            original = read_text(path)
        except OSError:
            continue
        chunk_applied = []
        updated = rewrite_text(original, chunk_applied)
        for item in chunk_applied:
            item["file"] = os.path.relpath(path, target)
            report["applied"].append(item)
        if updated != original:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(updated)

    skill_md_t = os.path.join(target, "SKILL.md")
    t = read_text(skill_md_t)
    _, body_t, has_fm = parse_frontmatter(t)
    with open(skill_md_t, "w", encoding="utf-8") as fh:
        fh.write(dump_frontmatter(fm_norm) + "\n" + body_t.lstrip("\n"))
    report["out"] = target
    report["body_bytes"] = len(body_t.encode("utf-8"))
    if report["body_bytes"] > BODY_SOFT_LIMIT:
        report["problems"].append(f"正文 {report['body_bytes']} B 超过软上限 {BODY_SOFT_LIMIT}，考虑拆 references/")
    return report


def validate(path):
    checker = os.path.expanduser("~/.dsh/skills/skill-creator/scripts/quick_validate.py")
    if not os.path.isfile(checker) or not os.path.isdir(path):
        return None
    proc = subprocess.run([sys.executable, checker, path], capture_output=True, text=True)
    return {"code": proc.returncode, "out": (proc.stdout + proc.stderr).strip()}


def render_md(report):
    lines = [f"# migrate 报告：{report['name']}", ""]
    lines += TIER_LEGEND
    lines += ["", f"- 源：`{report['source']}`"]
    if report.get("out"):
        lines += [f"- 产出：`{report['out']}`", f"- 正文：{report.get('body_bytes', '?')} B"]
    if report["problems"]:
        lines += ["", "## C 级 · 必须先解决"]
        lines += [f"- [ ] {p}" for p in report["problems"]]
    if report["applied"]:
        lines += ["", "## A 级 · 已自动改写"]
        for a in report["applied"]:
            where = f" · {a['file']}" if a.get("file") else ""
            lines.append(f"- `{a['rule']}` ×{a['count']}{where}")
    unsupported = [h for h in report["hits"] if h["severity"] == "UNSUPPORTED"]
    rewrites = [h for h in report["hits"] if h["severity"] == "REWRITE"]
    warns = [h for h in report["hits"] if h["severity"] == "WARN"]
    if unsupported:
        lines += ["", "## C 级 · DSH 没有对应物（原样保留）"]
        grouped = {}
        for h in unsupported:
            grouped.setdefault(h["rule"], []).append(h)
        for rule, hs in grouped.items():
            lines.append(f"- `{rule}` ×{len(hs)} — {hs[0]['note']}")
            for h in hs[:6]:
                loc = os.path.relpath(h["file"], report["source"]) if os.path.isdir(report["source"]) else os.path.basename(h["file"])
                lines.append(f"    - {loc}:{h['line']} `{h['match']}`")
    if rewrites and not report.get("out"):
        lines += ["", "## A 级 · 可自动改写（未写盘）"]
        grouped = {}
        for h in rewrites:
            grouped.setdefault(h["rule"], 0)
            grouped[h["rule"]] += 1
        lines += [f"- `{r}` ×{c} — {next(h['note'] for h in rewrites if h['rule'] == r)}" for r, c in grouped.items()]
    soft = list(report.get("warnings") or [])
    if soft or warns:
        lines += ["", "## B 级 · 建议处理（不拦人）"]
        for w in soft:
            lines.append(f"- {w}")
        grouped = {}
        for h in warns:
            grouped.setdefault(h["rule"], []).append(h)
        for rule, hs in grouped.items():
            lines.append(f"- `{rule}` ×{len(hs)} — {hs[0]['note']}")
    lines += render_requires(report.get("requires") or {})
    if report.get("validate"):
        v = report["validate"]
        lines += ["", "## quick_validate", "```", v["out"], "```"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Codex/Claude skill → DSH skill 迁移器")
    ap.add_argument("src", help="源 skill 目录，或单个 .md 技能文件")
    ap.add_argument("--out", default=os.path.expanduser("~/.dsh/skills"), help="输出根（默认 ~/.dsh/skills）")
    ap.add_argument("--apply", action="store_true", help="真的写盘并做自动改写")
    ap.add_argument("--report", help="把 PORT.md 写到这个路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--no-validate", action="store_true", help="跳过 quick_validate")
    ap.add_argument("--emit-sh", metavar="FILE",
                    help="生成 preflight.sh：把技能需要的工具/包/变量/路径逐条检查（只查不装）")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        log(f"[x] 源不存在: {args.src}")
        return 2

    report = port(args.src, args.out, args.apply)
    if report is None:
        return 2
    if args.apply and not args.no_validate and report.get("out"):
        report["validate"] = validate(report["out"])

    if args.emit_sh:
        emit_preflight(report.get("requires") or {}, report["name"], args.emit_sh)
        log(f"[ok] preflight → {args.emit_sh}")

    md = render_md(report)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(md)
        log(f"[ok] 报告 → {args.report}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(md)
    bad = any(h["severity"] == "UNSUPPORTED" for h in report["hits"]) or bool(report["problems"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
