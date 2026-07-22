#!/usr/bin/env python3
"""从原型解析数据生成页面跳转关系图 Markdown 文件。

用法：
    python3 scripts/generate_page_flow.py <解析JSON> [输出路径]

输入：parse_axure.py --json 输出的 JSON 文件路径
输出：页面跳转关系图.md（含 Mermaid 流程图）
"""
import json
import os
import re
import sys
import datetime


def infer_jumps_for_page(page, all_pages):
    """推断页面的跳转出口。"""
    jumps = []
    from_page = page['pageName']
    notes = page.get('notes', [])
    notes_text = '; '.join(notes) if notes else ''

    # 规则1：从 onClick 交互事件提取
    for evt in page.get('interactions', []):
        target = infer_jump_target(
            evt.get('description', ''), all_pages)
        if target:
            jumps.append({
                'from': from_page, 'to': target,
                'control': evt.get('description', '')[:20],
                'control_type': '交互事件',
                'condition': evt.get('event', 'onClick'),
                'note': notes_text[:30] if notes_text else '-',
            })

    # 规则2：从控件文字推断跳转
    page_names = {p['pageName'] for p in all_pages}
    for w in page.get('widgets', []):
        label = w.get('label', '') or w.get('name', '')
        if not label:
            continue
        for verb in ['新增', '编辑', '详情', '发布', '版本',
                     '模板', '认证', '概览']:
            if verb in label and any(verb in pn for pn in page_names):
                target = next(pn for pn in page_names if verb in pn)
                jumps.append({
                    'from': from_page, 'to': target,
                    'control': label[:20],
                    'control_type': w.get('friendlyType', '') or w.get('type', '按钮'),
                    'condition': '点击',
                    'note': notes_text[:30] if notes_text else '-',
                })
                break

    # 规则3：从页面名本身推断（如"新增节点"从"实例管理"跳转）
    if any(verb in from_page for verb in ['新增', '详情']):
        base = re.sub(r'[新增详情]', '', from_page)
        if any(p['pageName'] == base for p in all_pages):
            jumps.append({
                'from': base, 'to': from_page,
                'control': f'进入{from_page}',
                'control_type': '推断',
                'condition': '推断',
                'note': '基于页面名推断',
            })

    return jumps


def infer_jump_target(description, all_pages):
    """从交互描述推断跳转目标。"""
    page_names = [p['pageName'] for p in all_pages]
    for pn in page_names:
        if pn in description:
            return pn
    return None


def infer_isolation_reason(page):
    """推断孤立页面原因。"""
    name = page['pageName']
    if not page.get('texts') and not page.get('widgets'):
        return '原型未提供内容'
    if any(kw in name for kw in ['概述', '概览', '业务', '流程']):
        return '独立展示页'
    if not page.get('interactions'):
        return '未定义交互事件'
    return '无明确跳转出口'


def generate_page_flow_md(pages, output_path):
    """生成页面跳转关系图 md 文件。"""
    lines = ['# 页面跳转关系图', '', '## 1. 文档信息',
             '- 版本：v1.0',
             f'- 日期：{datetime.date.today().isoformat()}',
             '- 数据来源：原型解析', '']

    # 收集所有跳转关系
    all_jumps = []
    for page in pages:
        jumps = infer_jumps_for_page(page, pages)
        all_jumps.extend(jumps)

    # 页面总览
    lines.append('## 2. 页面总览')
    lines.append('')
    lines.append('| 页面名 | 文件 | 含交互事件 | 跳转目标数 |')
    lines.append('|--------|------|-----------|-----------|')
    for page in pages:
        has_interaction = bool(page.get('interactions'))
        jump_count = sum(1 for j in all_jumps
                         if j['from'] == page['pageName'])
        lines.append(
            f'| {page["pageName"]} | {page.get("url", "")} | '
            f'{"是" if has_interaction else "否"} | {jump_count} |'
        )
    lines.append('')

    # Mermaid 跳转关系图
    lines.append('## 3. 跳转关系图（Mermaid）')
    lines.append('')
    layout = 'TD' if len(pages) <= 10 else 'LR'
    lines.append('```mermaid')
    lines.append(f'graph {layout}')
    id_map = {}
    for i, page in enumerate(pages):
        pid = f'P{i+1}'
        id_map[page['pageName']] = pid
        lines.append(f'  {pid}["{page["pageName"]}"]')
    for jump in all_jumps:
        from_id = id_map.get(jump['from'])
        to_id = id_map.get(jump['to'])
        if from_id and to_id:
            label = jump.get('condition', '')[:20]
            lines.append(f'  {from_id} -->|{label}| {to_id}')
    lines.append('```')
    lines.append('')

    # 跳转关系详表
    lines.append('## 4. 跳转关系详表')
    lines.append('')
    by_page = {}
    for j in all_jumps:
        by_page.setdefault(j['from'], []).append(j)

    for page_name, jumps in by_page.items():
        lines.append(f'### [{page_name}]')
        lines.append('')
        lines.append('| 出口控件 | 控件类型 | 跳转条件 | 目标页面 | 备注 |')
        lines.append('|---------|---------|---------|---------|------|')
        for j in jumps:
            lines.append(
                f'| {j.get("control", "")} | {j.get("control_type", "")} | '
                f'{j.get("condition", "")} | {j.get("to", "")} | '
                f'{j.get("note", "-")} |'
            )
        lines.append('')

    # 孤立页面
    lines.append('## 5. 孤立页面')
    lines.append('')
    connected = set()
    for j in all_jumps:
        connected.add(j['from'])
        connected.add(j['to'])
    isolated = [p for p in pages if p['pageName'] not in connected]
    if isolated:
        lines.append('| 页面名 | 可能原因 | 建议 |')
        lines.append('|--------|---------|------|')
        for p in isolated:
            reason = infer_isolation_reason(p)
            suggestion = '补充跳转关系' if reason != '独立展示页' else '可保留为独立页'
            lines.append(f'| {p["pageName"]} | {reason} | {suggestion} |')
    else:
        lines.append('无孤立页面，所有页面均有跳转关系。')
    lines.append('')

    # 数据来源说明
    notes_included = any(p.get('notes') for p in pages)
    lines.append('## 6. 数据来源说明')
    if notes_included:
        lines.append('- 便签/矩形内备注说明已纳入跳转条件与备注列')
    lines.append('- 跳转关系优先来自 onClick 交互事件，'
                 '其次从按钮文字/链接推断')
    lines.append('- 孤立页面可能因原型未定义跳转，需结合实际业务确认')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    if len(sys.argv) < 2:
        print('用法：python3 scripts/generate_page_flow.py <解析JSON> [输出路径]',
              file=sys.stderr)
        sys.exit(1)
    json_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else '页面跳转关系图.md'

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    pages = data.get('pages', [])

    generate_page_flow_md(pages, output_path)
    print(f'✓ 已生成 {output_path}（{len(pages)} 页面）')


if __name__ == '__main__':
    main()
