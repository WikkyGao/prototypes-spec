# prototypes-spec · 项目全局规则

> 本文件对所有在本仓库工作的 Agent 生效（Claude Code / Codex / ZCode / Cursor / Gemini / AtomCode 等均读取根目录 `AGENTS.md` 或 `CLAUDE.md`）。

## 发布链路：git 提交后默认执行完整发布

在本仓库**只要产生 git commit，默认视为一次发布**：提交后必须依次完成下面 4 步，不得止步于本地 commit。

**唯一例外**：commit message 含 `[no-release]` 标记，或用户明确说「只提交不发布」。

### 0. 前置检查

- 版本号以 `package.json` / `_meta.json` / `SKILL.md` 三处为准，必须一致，不一致先改齐再提交
- 本次提交含功能 / 修复变更 → 先按语义 bump 版本（patch / minor / major）再提交
- 纯文档 / 规则 / 示例变更可不 bump 版本

### 1. 推送所有远端

```bash
git push github master && git push gitee master
```

### 2. 发布 skillhub.cn

- 若版本号与线上 `latest` 相同 → **跳过发布**（平台不允许同版本重发，需要重发先 bump 版本）
- 否则打包并发布。**平台仅接受文本类文件**，`prototypes-spec.skill`（zip 二进制）、`.DS_Store` 等会被 400 拒绝，必须排除：

```bash
VER=$(python3 -c "import json;print(json.load(open('package.json'))['version'])")
rm -f /tmp/prototypes-spec-hub-$VER.zip
zip -rq /tmp/prototypes-spec-hub-$VER.zip . -x ".git/*" ".mimosa/*" ".atomcode/*" ".DS_Store" "*/.DS_Store" "prototypes-spec.skill" "*.zip"
skillhub publish /tmp/prototypes-spec-hub-$VER.zip --version $VER --changelog "<本次变更摘要>" --json
```

- 发布返回 JSON 中 `tags.latest` 必须已指向新版本；`reviewStatus: pending` 属正常（审核异步）
- 仓库内 `prototypes-spec.skill` 是本地分发用的打包文件，发布前用 `cd /tmp && unzip -o` 之类方式重新生成即可，不参与 skillhub 发布

### 3. 更新所有本地 Agent（按 `~/Documents/skills/本地已安装Agent清单.md`）

实体副本共 4 份，用仓库自带脚本 rsync 镜像（其余约 21 个 agent 均为软链，自动跟随，无需处理）：

```bash
./deploy.sh
```

- 软链跟随说明：`~/.atomcode/skills/prototypes-spec` 直接链到本源码仓库；`~/.claude/skills/prototypes-spec` 经 magpie library 链到 `~/.agents/skills/prototypes-spec`，均自动生效
- `~/.codex/skills/prototypes-spec` 若缺失，按清单一律恢复为指向 cc-switch 的软链：
  `ln -s ~/.cc-switch/skills/prototypes-spec ~/.codex/skills/prototypes-spec`
- 同步后全量验证 26 个 agent 目录版本一致：

```bash
for d in ~/.dsh/skills ~/.agents/skills ~/.cc-switch/skills ~/.claude/skills ~/.codex/skills ~/.gemini/skills ~/.gemini/antigravity/skills ~/.config/opencode/skills ~/.cursor/skills ~/.copilot/skills ~/.qoder/skills ~/.qoder-cn/skills ~/.qoderwork/skills ~/.codeartsdoer/skills ~/.minimax/skills ~/.mavis/skills ~/.pencil/skills ~/.reasonix/skills ~/.workbuddy/skills ~/.workbuddy-ai/skills ~/.codebuddy/skills ~/.kiro/skills ~/.zcode/skills ~/.pi/agent/skills ~/.atomcode/skills ~/.agnes/skills; do
  p="$d/prototypes-spec"
  [ -e "$p" ] && python3 -c "import json;v=json.load(open('$p/package.json'))['version'];assert v=='$VER',v" && echo "OK $p" || echo "FAIL $p"
done
```

- 有 `FAIL` / `MISS` 必须修复后重验，不得带病交付
- deploy.sh 输出的 `deleting` 列表先人工确认（应为源仓库已删除的遗留文件），再实跑

### 4. 更新清单文档

在 `~/Documents/skills/本地已安装Agent清单.md` 更新：

- 表头统计（统计日期、技能版本、结论）
- 「一、全局 Agent 技能目录」表中的版本列
- 「四、源码与发布状态」：当前提交、分支、工作区、SkillHub 发布状态、打包文件大小
- 实体副本与软链 agent 名单有变化时同步修正
