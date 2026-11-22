---
name: commit_helper
description: 从暂存区改动生成符合约定的提交信息，用于验证 name 归一化与 when-to-use 迁移
when-to-use: 需要写一条提交信息时
---

# Commit Helper

读取 `git diff --cached`，输出一条 conventional commit 信息。

约定参考 `/Users/someone/.claude/commands/commit.md` 的旧版本。
