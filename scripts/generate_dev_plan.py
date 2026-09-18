#!/usr/bin/env python3
"""从原型解析数据生成开发计划 Markdown 文件。

用法：
    python3 scripts/generate_dev_plan.py <解析JSON> [输出路径]

输入：parse_axure.py --json 输出的 JSON 文件路径
输出：开发计划.md
"""
import json
import os
import re
import sys
import datetime
from pathlib import Path


def infer_feature_count(page):
    """推断页面功能数。"""
    count = 1
    count += len(page.get('widgets', [])) // 3
    count += len(page.get('interactions', []))
    return min(count, 10)


def infer_module_priority(page):
    """推断模块优先级。"""
    name = page['pageName']
    if any(kw in name for kw in ['管理', '新增', '配置', '认证']):
        return 'P0'
    elif any(kw in name for kw in ['详情', '版本', '发布']):
        return 'P1'
    else:
        return 'P2'


def calc_work_days(module):
    """计算预估工时。"""
    base = module['feature_count']
    if module['priority'] == 'P0':
        days = base * 1.0
    elif module['priority'] == 'P1':
        days = base * 0.5
    else:
        days = base * 0.3
    if module['notes']:
        days *= 1.2
    return round(days, 1)


def infer_role(module):
    """推断负责角色。"""
    widget_types = [w.get('friendlyType', '') or w.get('type', '')
                    for w in module['widgets']]
    if any('认证' in n or 'Token' in n for n in module['notes']):
        return '后端'
    if '表格' in widget_types or '树' in widget_types:
        return '前后端'
    if '输入框' in widget_types:
        return '前端'
    return '前端'


def infer_dependencies(page, all_pages):
    """推断模块依赖。"""
    deps = []
    name = page['pageName']
    if '新增' in name and any(p['pageName'] == '实例管理' for p in all_pages):
        deps.append('实例管理')
    if '详情' in name:
        base = name.replace('详情', '')
        if any(p['pageName'] == base for p in all_pages):
            deps.append(base)
    return deps


def infer_milestones(modules):
    """推断里程碑。"""
    p0 = [m for m in modules if m['priority'] == 'P0']
    p1 = [m for m in modules if m['priority'] == 'P1']
    p2 = [m for m in modules if m['priority'] == 'P2']
    return [
        {
            'name': 'M1 - 核心框架', 'schedule': '第 1-2 周',
            'deliver': ', '.join(m['name'] for m in p0[:3]) or '概述/框架',
            'entry': '项目启动',
        },
        {
            'name': 'M2 - 主功能', 'schedule': '第 3-5 周',
            'deliver': ', '.join(m['name'] for m in p0[3:]) or '主功能模块',
            'entry': 'M1 完成',
        },
        {
            'name': 'M3 - 配套功能', 'schedule': '第 6-7 周',
            'deliver': ', '.join(m['name'] for m in p1) or '配套功能',
            'entry': 'M2 完成',
        },
        {
            'name': 'M4 - 优化收尾', 'schedule': '第 8 周',
            'deliver': ', '.join(m['name'] for m in p2) or '优化收尾',
            'entry': 'M3 完成',
        },
    ]


def infer_risks(modules):
    """推断风险项。"""
    risks = []
    for m in modules:
        for note in m['notes']:
            if any(kw in note for kw in ['有效期', '验证', '必须', '只能', '不可']):
                risks.append({
                    'module': m['name'],
                    'risk': f'备注说明的业务规则需确认实现：{note[:40]}',
                })
        if not m['widgets'] and not m['texts']:
            risks.append({
                'module': m['name'],
                'risk': '原型未提供文本内容，功能需用户补充说明',
            })
    return risks


def generate_dev_plan_md(pages, output_path):
    """生成开发计划 md 文件。"""
    lines = ['# 开发计划', '', '## 1. 计划信息',
             '- 版本：v1.0',
             f'- 日期：{datetime.date.today().isoformat()}',
             '- 数据来源：原型解析', '']

    # 模块拆分
    modules = []
    for page in pages:
        module = {
            'name': page['pageName'],
            'feature_count': infer_feature_count(page),
            'priority': infer_module_priority(page),
            'notes': page.get('notes', []),
            'widgets': page.get('widgets', []),
            'texts': page.get('texts', []),
            'interactions': page.get('interactions', []),
        }
        module['work_days'] = calc_work_days(module)
        module['role'] = infer_role(module)
        module['dependencies'] = infer_dependencies(page, pages)
        modules.append(module)

    modules.sort(key=lambda m: (
        {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}.get(m['priority'], 9),
        len(m['dependencies']),
    ))

    lines.append('## 2. 项目概述')
    lines.append(f'本项目共包含 {len(modules)} 个模块，'
                 f'预估总工时 {sum(m["work_days"] for m in modules)} 人天。')
    lines.append('')
    lines.append('## 3. 模块拆分与排期')
    lines.append('')
    lines.append('| 模块名 | 功能数 | 优先级 | 预估工时 | 依赖模块 | '
                 '负责角色 | 备注 |')
    lines.append('|--------|--------|--------|---------|---------|---------|------|')
    for m in modules:
        note_text = '; '.join(m['notes']) if m['notes'] else '-'
        lines.append(
            f'| {m["name"]} | {m["feature_count"]} | {m["priority"]} | '
            f'{m["work_days"]} 人天 | {", ".join(m["dependencies"]) or "-"} | '
            f'{m["role"]} | {note_text[:30]} |'
        )
    lines.append('')

    lines.append('## 4. 里程碑计划')
    lines.append('')
    lines.append('| 里程碑 | 时间节点 | 交付内容 | 入口标准 |')
    lines.append('|--------|---------|---------|---------|')
    for ms in infer_milestones(modules):
        lines.append(f'| {ms["name"]} | {ms["schedule"]} | {ms["deliver"]} | '
                     f'{ms["entry"]} |')
    lines.append('')

    lines.append('## 5. 风险与待确认项')
    lines.append('')
    risks = infer_risks(modules)
    for r in risks:
        lines.append(f'- **{r["module"]}**：{r["risk"]}')
    if not risks:
        lines.append('- 无明确风险项')
    lines.append('')

    notes_included = any(m['notes'] for m in modules)
    lines.append('## 6. 数据来源说明')
    if notes_included:
        lines.append('- 便签/矩形内备注说明已纳入模块备注与风险评估')
    lines.append('- 工时为基于功能数的估算值，需开发团队确认')
    lines.append('- 模块依赖关系基于页面跳转推断，需结合实际业务确认')

    # 规范化并校验输出路径，仅允许写入当前工作目录内，防止路径穿越
    base = os.path.realpath(os.getcwd())
    output_path = os.path.realpath(output_path)
    if output_path != base and not output_path.startswith(base + os.sep):
        raise SystemExit(f'输出路径越界，仅允许写入当前工作目录内：{output_path}')
    os.makedirs(os.path.dirname(output_path) or base, exist_ok=True)

    Path(output_path).write_text('\n'.join(lines), encoding='utf-8')


def main():
    if len(sys.argv) < 2:
        print('用法：python3 scripts/generate_dev_plan.py <解析JSON> [输出路径]',
              file=sys.stderr)
        sys.exit(1)
    json_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else '开发计划.md'

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    pages = data.get('pages', [])

    generate_dev_plan_md(pages, output_path)
    print(f'✓ 已生成 {output_path}（{len(pages)} 页面）')


if __name__ == '__main__':
    main()
