#!/usr/bin/env python3
"""migrate_skill.py 的回归测试：只依赖标准库，CI 与本机跑法一致。

    python3 tests/run_tests.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "migrate_skill.py")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

failures = []


def run(src, *extra):
    cmd = [sys.executable, SCRIPT, src, "--json", *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout[proc.stdout.index("{"):])
    except (ValueError, json.JSONDecodeError):
        raise AssertionError(f"非 JSON 输出：stdout={proc.stdout[:400]} stderr={proc.stderr[:400]}")
    return proc.returncode, data


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
        return
    failures.append(f"{name} {detail}".strip())
    print(f"  FAIL {name} {detail}")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_dry_run_flags_codex_leftovers():
    print("dry-run 检出 Codex 残留")
    rc, r = run(os.path.join(FIXTURES, "codex-sample"))
    rules = {h["rule"] for h in r["hits"]}
    check("退出码 1（有问题）", rc == 1, f"rc={rc}")
    check("检出 image_gen", "tool-image-gen" in rules)
    check("检出 view_image", "tool-view-image" in rules)
    check("检出 agents/openai.yaml", "openai-yaml" in rules or "openai-yaml-file" in rules, str(sorted(rules)))
    check("检出 $CODEX_HOME", "codex-home-env" in rules, str(sorted(rules)))
    check("检出 short-description", "fm-short-desc" in rules)
    check("干跑不写盘", r.get("out") is None)


def test_apply_rewrites_and_normalizes():
    print("--apply 改写路径并归一化 frontmatter")
    tmp = tempfile.mkdtemp(prefix="port-test-")
    try:
        out = os.path.join(tmp, "out")
        rc, r = run(os.path.join(FIXTURES, "codex-sample"), "--out", out, "--apply")
        target = os.path.join(out, "image-gen-legacy")
        check("按 kebab 名落盘", os.path.isdir(target), r.get("out") or "")
        if not os.path.isdir(target):
            return
        skill = read(os.path.join(target, "SKILL.md"))
        check("frontmatter name 已归一", "name: image-gen-legacy" in skill, skill[:80])
        check("short-description 进 metadata", "short-description" in skill.split("---")[1])
        fetch = read(os.path.join(target, "scripts", "fetch.py"))
        check("脚本改为 DSH_HOME", "DSH_HOME" in fetch and "CODEX_HOME" not in fetch, fetch)
        check("脚本 home 指向 ~/.dsh", "~/.dsh" in fetch)
        body = read(os.path.join(target, "SKILL.md"))
        check("正文 $CODEX_HOME → $DSH_HOME", "$DSH_HOME" in body and "$CODEX_HOME" not in body)
        check("改完仍有 UNSUPPORTED（image_gen 不会被静默吞掉）",
              any(h["severity"] == "UNSUPPORTED" for h in r["hits"]) and rc == 1, f"rc={rc}")
        check("agents/openai.yaml 保留原样，等人处置",
              os.path.isfile(os.path.join(target, "agents", "openai.yaml")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_clean_input_stays_quiet():
    print("干净输入不报假警")
    rc, r = run(os.path.join(FIXTURES, "clean-sample"))
    check("退出码 0", rc == 0, f"rc={rc}")
    check("无命中", r["hits"] == [], str(r["hits"])[:200])
    check("无必须先解决的问题", r["problems"] == [], str(r["problems"]))


def test_claude_frontmatter_keys():
    print("Claude 风格 frontmatter 归一化")
    tmp = tempfile.mkdtemp(prefix="port-test-")
    try:
        out = os.path.join(tmp, "out")
        rc, r = run(os.path.join(FIXTURES, "claude-sample"), "--out", out, "--apply")
        target = os.path.join(out, "commit-helper")
        check("name 下划线转 kebab", os.path.isdir(target), str(r.get("out")))
        if not os.path.isdir(target):
            return
        skill = read(os.path.join(target, "SKILL.md"))
        fm = skill.split("---")[1]
        check("when-to-use 进 metadata", "when-to-use" in fm)
        check("正文完整保留", "conventional commit" in skill)
        check("WARN 不影响退出码", rc == 0, f"rc={rc}")
        rules = {h["rule"] for h in r["hits"]}
        check("检出个人绝对路径", "abs-home-path" in rules, str(sorted(rules)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_long_description_is_warning_not_blocker():
    print("description 超长只提醒、不拦截")
    rc, r = run(os.path.join(FIXTURES, "long-desc-sample"))
    check("退出码 0", rc == 0, f"rc={rc}")
    check("不阻塞", r["problems"] == [], str(r["problems"]))
    check("有软提醒", any("fm-desc-long" in w for w in r.get("warnings", [])), str(r.get("warnings")))


def test_claude_advanced_workflows_are_flagged():
    print("Claude 高级工作流不被静默丢")
    rc, r = run(os.path.join(FIXTURES, "claude-advanced-sample"))
    rules = {h["rule"] for h in r["hits"]}
    check("退出码 1（有必须先解决的）", rc == 1, f"rc={rc}")
    check("检出 hooks", "claude-hooks" in rules, str(sorted(rules)))
    check("检出 subagent", "claude-subagent" in rules, str(sorted(rules)))
    check("列为 DSH 无对应物",
          any(h["rule"] in {"claude-hooks", "claude-subagent"} and h["severity"] == "UNSUPPORTED"
              for h in r["hits"]), str(r["hits"])[:200])


def test_requires_extraction_and_preflight():
    print("抽取依赖清单并生成可跑的 preflight.sh")
    rc, r = run(os.path.join(FIXTURES, "requires-sample"))
    req = r["requires"]
    names = lambda k: {i["name"] for i in req.get(k) or []}
    check("抽出 pip 包", "pikepdf" in names("python"), str(names("python")))
    check("抽出 brew 包", "ghostscript" in names("brew"), str(names("brew")))
    check("抽出环境变量", "PDF_OUT" in names("env"), str(names("env")))
    check("家目录路径展开为 $HOME", any("$HOME" in i["check"] for i in req["paths"]), str(req["paths"]))
    check("抽出 MCP 服务器", "rea" in names("mcp"), str(names("mcp")))
    check("不因依赖清单而判失败", rc == 0, f"rc={rc}")

    tmp = tempfile.mkdtemp(prefix="preflight-test-")
    try:
        sh = os.path.join(tmp, "preflight.sh")
        run(os.path.join(FIXTURES, "requires-sample"), "--emit-sh", sh)
        content = read(sh)
        check("脚本只查不装", "pip install pikepdf" in content and "then " in content, content[:120])
        check("脚本可执行位", os.access(sh, os.X_OK), oct(os.stat(sh).st_mode))
        proc = subprocess.run(["sh", sh], capture_output=True, text=True)
        check("缺依赖时退出码非 0", proc.returncode > 0, str(proc.returncode))
        check("输出带补救提示", "→" in proc.stdout, proc.stdout[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tiers_abc_are_reported():
    print("每条问题都标了 A/B/C 档")
    rc, r = run(os.path.join(FIXTURES, "codex-sample"))
    tiers = {h["tier"] for h in r["hits"]}
    check("JSON 里带 tier 字段", tiers and tiers <= {"A", "B", "C"}, str(sorted(tiers)))
    check("自动改写的算 A", any(h["tier"] == "A" and h["severity"] == "REWRITE" for h in r["hits"]))
    check("必须人处置的算 C", any(h["tier"] == "C" and h["severity"] == "UNSUPPORTED" for h in r["hits"]))
    check("建议的算 B", any(h["tier"] == "B" and h["severity"] == "WARN" for h in r["hits"]))

    proc = subprocess.run([sys.executable, SCRIPT, os.path.join(FIXTURES, "codex-sample")],
                          capture_output=True, text=True)
    md = proc.stdout
    for marker in ("A 级", "B 级", "C 级"):
        check(f"报告正文解释了 {marker}", marker in md)
    check("C 级段落说明原样保留", "原样保留" in md, md[:400])


def test_prose_and_namespaces_are_not_dependencies():
    print("正文散文和 XML 命名空间不算依赖")
    rc, r = run(os.path.join(FIXTURES, "noise-sample"))
    tools = {i["name"] for i in r["requires"]["tools"]}
    check("散文里的 which restores 不算工具", "restores" not in tools, str(sorted(tools)))
    check("散文里的 which the 不算工具", "the" not in tools, str(sorted(tools)))
    check("代码块里的 python3 算工具", "python3" in tools, str(sorted(tools)))
    urls = {i["name"] for i in r["requires"]["urls"]}
    check("命名空间 URL 被过滤", not any("openxmlformats" in u or "openoffice" in u for u in urls), str(sorted(urls)))
    pips = {i["name"] for i in r["requires"]["python"]}
    check("代码块里的 pip 包照常抽出", "python-docx" in pips, str(sorted(pips)))


def test_non_shell_fences_and_todo_prose():
    print("非 shell 代码块与正文 TODO 不算问题")
    rc, r = run(os.path.join(FIXTURES, "lang-sample"))
    tools = {i["name"] for i in r["requires"]["tools"]}
    check("swift 代码块里的 content 不算工具", "content" not in tools, str(sorted(tools)))
    check("bash 代码块里的 xcodebuild 算工具", "xcodebuild" in tools, str(sorted(tools)))
    rules = {h["rule"] for h in r["hits"]}
    check("正文 TODO list 不算占位符", "todo-placeholder" not in rules, str(sorted(rules)))


def main():
    for fn in (
        test_dry_run_flags_codex_leftovers,
        test_apply_rewrites_and_normalizes,
        test_clean_input_stays_quiet,
        test_claude_frontmatter_keys,
        test_long_description_is_warning_not_blocker,
        test_claude_advanced_workflows_are_flagged,
        test_requires_extraction_and_preflight,
        test_tiers_abc_are_reported,
        test_prose_and_namespaces_are_not_dependencies,
        test_non_shell_fences_and_todo_prose,
    ):
        fn()
    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
