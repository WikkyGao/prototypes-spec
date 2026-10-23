# prototypes-spec · Claude Code 规则

本项目全局规则见 @AGENTS.md

**核心规则：在本仓库产生 git commit 后，默认必须执行完整发布链路**——推送所有远端（github + gitee）→ 发布 skillhub.cn（版本未变则跳过）→ `./deploy.sh` 更新全部本地 agent 实体副本并验证 26/26 → 更新 `~/Documents/skills/本地已安装Agent清单.md`。唯一例外：commit message 含 `[no-release]` 或用户明确说「只提交不发布」。
