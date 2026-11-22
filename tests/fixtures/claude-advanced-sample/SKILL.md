---
name: commit-guard
description: 提交前跑一遍检查，并调用一个专门的 review subagent 看 diff。
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/guard.sh"
---

# 提交前检查

1. 运行 `./scripts/check.sh`
2. 用 Task(subagent_type="reviewer") 看一眼 diff
3. 参考 `.claude/agents/reviewer.md` 的判定标准
