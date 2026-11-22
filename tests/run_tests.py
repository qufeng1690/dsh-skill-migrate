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


def main():
    for fn in (
        test_dry_run_flags_codex_leftovers,
        test_apply_rewrites_and_normalizes,
        test_clean_input_stays_quiet,
        test_claude_frontmatter_keys,
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
