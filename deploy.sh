#!/bin/bash
# 将本仓库（skill 源）同步到各 Agent 的 skill 部署目录。
# 背景：ZCode/Claude 等加载的是 ~/.zcode/skills、~/.agents/skills 下的拷贝，
# 不同步则开发仓库的新规则永远不会生效（2026-09-18 测试时踩坑）。
# 用法: ./deploy.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DESTS=(
  "$HOME/.zcode/skills/prototypes-spec"
  "$HOME/.agents/skills/prototypes-spec"
)

for DEST in "${DESTS[@]}"; do
  mkdir -p "$DEST"
  rsync -av \
    --exclude '.git' \
    --exclude '.DS_Store' \
    --exclude '.mimosa' \
    --exclude 'OPTIMIZATION_PLAN.md' \
    --exclude 'deploy.sh' \
    "$SRC/" "$DEST/"
  echo "✓ 已同步 → $DEST"
done

echo
echo "校验（三处 SKILL.md 指纹应一致）:"
md5 -q "$SRC/SKILL.md" "${DESTS[@]/%//SKILL.md}"
