#!/usr/bin/env python3
"""从原型解析数据生成用户故事 Markdown 文件。

用法：
    python3 scripts/generate_user_stories.py <解析JSON> [输出路径]

输入：parse_axure.py --json 输出的 JSON 文件路径
输出：用户故事.md（含角色定义 + 故事地图 + 详表 + 验收标准汇总）
"""
import json
import os
import re
import sys
import datetime


def infer_roles(pages):
    """从原型识别用户角色。"""
    roles = []
    role_keywords = {
        '运维': {'管理', '实例', '部署', '发布'},
        '开发': {'配置', '版本', '模板', '注册'},
        '系统管理员': {'认证', '权限', '授权', 'Admin'},
    }

    for role_name, keywords in role_keywords.items():
        related_pages = []
        for page in pages:
            name = page['pageName']
            if any(kw in name for kw in keywords):
                related_pages.append(name)
        if related_pages:
            rid = f'R{len(roles) + 1}'
            notes_for_role = []
            for page in pages:
                if page['pageName'] in related_pages:
                    notes_for_role.extend(page.get('notes', []))
            roles.append({
                'id': rid, 'name': role_name,
                'desc': f'负责{role_name}相关功能',
                'pages': related_pages[:3],
                'note': '; '.join(notes_for_role[:2]) if notes_for_role else '-',
            })

    if not roles:
        roles.append({
            'id': 'R1', 'name': '普通用户',
            'desc': '（推测）原型未明确角色',
            'pages': [pages[0]['pageName']] if pages else [],
            'note': '推测角色',
        })
    return roles


def infer_story_title(page):
    """推断故事标题。"""
    module = page['pageName']
    if '管理' in module:
        return f'查看{module}列表'
    elif '新增' in module:
        return f'新增{module.replace("新增", "")}'
    elif '详情' in module:
        return f'查看{module.replace("详情", "详情")}'
    else:
        return f'查看{module}'


def infer_story_feature(page):
    """推断故事功能描述。"""
    module = page['pageName']
    if page.get('texts'):
        return f'访问{module}页面，查看其中的内容'
    return f'使用{module}相关功能'


def infer_story_value(page, notes):
    """推断故事业务价值。"""
    module = page['pageName']
    if notes:
        return f'满足业务规则：{notes[0][:30]}'
    if '管理' in module:
        return f'掌握{module.replace("管理", "")}的完整信息'
    return f'完成{module}相关业务流程'


def infer_acceptance_criteria(page, notes):
    """推断验收标准。"""
    criteria = []
    module = page['pageName']

    if page.get('texts'):
        criteria.append(f'1. 进入{module}页，页面正常加载')
        for t in page.get('texts', [])[:3]:
            if t and not t.startswith('备注'):
                criteria.append(f'1. 页面显示"{t[:20]}"相关内容')

    for note in notes[:2]:
        criteria.append(f'1. 符合备注说明：{note}')

    if not criteria:
        criteria.append('1. （待补充，原型未提供明确验收标准）')

    return criteria


def infer_stories_for_page(page, roles, start_no):
    """为页面推断用户故事。"""
    stories = []
    module = page['pageName']
    notes = page.get('notes', [])
    notes_text = '; '.join(notes) if notes else ''

    # 规则1：每个角色至少一个主故事
    for role in roles:
        if module in role['pages'] or any(
            kw in module for kw in ['管理', '配置', '认证']
        ):
            story = {
                'id': f'US-{start_no:03d}', 'role': role['name'],
                'module': module,
                'title': infer_story_title(page),
                'feature': infer_story_feature(page),
                'value': infer_story_value(page, notes),
                'acceptance': infer_acceptance_criteria(page, notes),
                'priority': 'P0',
                'note': notes_text[:50] if notes_text else '',
            }
            stories.append(story)
            start_no += 1
            break

    # 规则2：从控件推断附加故事
    for w in page.get('widgets', [])[:5]:
        w_type = w.get('friendlyType', '') or w.get('type', '')
        if w_type == '输入框':
            stories.append({
                'id': f'US-{start_no:03d}',
                'role': stories[0]['role'] if stories else '普通用户',
                'module': module,
                'title': f'填写{w.get("label", "信息")}',
                'feature': f'在{w.get("label", "表单")}中填写信息',
                'value': '完成数据录入',
                'acceptance': ['输入框可正常输入', '提交后数据保存成功'],
                'priority': 'P1', 'note': '',
            })
            start_no += 1

    # 规则3：从备注说明补故事
    for note in notes[:2]:
        if any(kw in note for kw in ['有效期', '验证', '规则', '管理']):
            stories.append({
                'id': f'US-{start_no:03d}',
                'role': stories[0]['role'] if stories else '普通用户',
                'module': module,
                'title': f'管理：{note[:15]}',
                'feature': note, 'value': '符合业务规则约束',
                'acceptance': [f'按备注说明执行：{note}'],
                'priority': 'P1', 'note': '来自备注说明',
            })
            start_no += 1

    return stories


def generate_user_stories_md(pages, output_path):
    """生成用户故事 md 文件。"""
    lines = ['# 用户故事', '', '## 1. 文档信息',
             '- 版本：v1.0',
             f'- 日期：{datetime.date.today().isoformat()}',
             '- 数据来源：原型解析', '']

    # 识别角色
    roles = infer_roles(pages)
    lines.append('## 2. 角色定义')
    lines.append('')
    lines.append('| 角色编号 | 角色名 | 说明 | 出现页面 | 备注 |')
    lines.append('|---------|--------|------|---------|------|')
    for r in roles:
        lines.append(
            f'| {r["id"]} | {r["name"]} | {r["desc"]} | '
            f'{", ".join(r["pages"])} | {r.get("note", "-")} |'
        )
    lines.append('')

    # 生成所有故事
    all_stories = []
    story_no = 1
    for page in pages:
        page_stories = infer_stories_for_page(page, roles, story_no)
        all_stories.extend(page_stories)
        story_no += len(page_stories)

    # 用户故事地图
    lines.append('## 3. 用户故事地图')
    lines.append('')
    modules = list({s['module'] for s in all_stories})
    header = ('| 模块 \\\'角色 | '
              + ' | '.join(f'{r["id"]} {r["name"]}' for r in roles) + ' |')
    lines.append(header)
    lines.append('|' + '---|' * (len(roles) + 1))
    for module in modules:
        row = [f'**{module}**']
        for r in roles:
            stories_in = [s['id'] for s in all_stories
                          if s['module'] == module and s['role'] == r['name']]
            row.append(', '.join(stories_in) if stories_in else '-')
        lines.append('| ' + ' | '.join(row) + ' |')
    lines.append('')

    # 用户故事详表
    lines.append('## 4. 用户故事详表')
    lines.append('')
    by_role = {}
    for s in all_stories:
        by_role.setdefault(s['role'], []).append(s)

    for role_name, stories in by_role.items():
        lines.append(f'### 角色：{role_name}')
        lines.append('')
        for s in stories:
            lines.append(f'#### {s["id"]} {s["title"]}')
            lines.append('')
            lines.append(f'**作为** {s["role"]}')
            lines.append(f'**我想要** {s["feature"]}')
            lines.append(f'**以便于** {s["value"]}')
            lines.append('')
            lines.append('**验收标准：**')
            for ac in s['acceptance']:
                lines.append(ac)
            lines.append('')
            lines.append(f'**优先级：** {s["priority"]}')
            lines.append(f'**所属模块：** {s["module"]}')
            if s.get('note'):
                lines.append(f'**备注：** {s["note"]}')
            lines.append('')

    # 验收标准汇总
    lines.append('## 5. 验收标准汇总')
    lines.append('')
    for s in all_stories:
        lines.append(f'- **{s["id"]}**：')
        for ac in s['acceptance']:
            content = ac[2:].strip() if (ac.startswith('1.') or ac.startswith('2.')) else ac
            lines.append(f'  - {content}')
    lines.append('')

    notes_included = any(p.get('notes') for p in pages)
    lines.append('## 6. 数据来源说明')
    if notes_included:
        lines.append('- 便签/矩形内备注说明已纳入故事、验收标准与角色定义')
    lines.append('- 角色为基于原型内容的推断，需结合实际业务确认')
    lines.append('- 验收标准来自原型文本，未体现的标注为"待补充"')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    if len(sys.argv) < 2:
        print('用法：python3 scripts/generate_user_stories.py <解析JSON> [输出路径]',
              file=sys.stderr)
        sys.exit(1)
    json_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else '用户故事.md'

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    pages = data.get('pages', [])

    generate_user_stories_md(pages, output_path)
    print(f'✓ 已生成 {output_path}（{len(pages)} 页面）')


if __name__ == '__main__':
    main()
