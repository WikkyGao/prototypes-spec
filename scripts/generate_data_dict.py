#!/usr/bin/env python3
"""从原型解析数据生成数据字典 Markdown 文件。

用法：
    python3 scripts/generate_data_dict.py <解析JSON> [输出路径]

输入：parse_axure.py --json 输出的 JSON 文件路径
输出：数据字典.md
"""
import json
import os
import re
import sys
import datetime
from pathlib import Path


def to_camel_case(text):
    """中文转驼峰命名（简化示例）。"""
    clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z]', '', text)
    return 'field_' + clean[:10] if clean else 'unknown'


def infer_field_from_widget(widget, page_name, notes):
    """从控件推断字段定义。"""
    w_type = widget.get('friendlyType', '') or widget.get('type', '')
    label = widget.get('label', '') or widget.get('name', '')
    if not label:
        return None
    type_map = {
        '输入框': 'string', '文本框': 'text', '下拉列表': 'enum',
        '复选框': 'boolean', '单选按钮': 'enum',
    }
    field_type = type_map.get(w_type, 'string')
    return {
        'name': to_camel_case(label), 'label': label, 'type': field_type,
        'length': '-', 'required': '否', 'default': '-',
        'desc': label, 'page': page_name,
        'note': '; '.join(notes) if notes else '-',
    }


def infer_field_from_label_value(text, page_name, notes):
    """从"标签：值"格式文本推断字段。"""
    m = re.match(r'([^：:]+)[：:]\s*(.+)', text)
    if not m:
        return None
    label = m.group(1).strip()
    value = m.group(2).strip()
    return {
        'name': to_camel_case(label), 'label': label, 'type': 'string',
        'length': '-', 'required': '否',
        'default': value if value not in ('-', '——') else '-',
        'desc': label, 'page': page_name,
        'note': '; '.join(notes) if notes else '-',
    }


def generate_data_dictionary_md(pages, output_path):
    """生成数据字典 md 文件。"""
    lines = ['# 数据字典', '', '## 1. 文档信息',
             '- 版本：v1.0',
             f'- 日期：{datetime.date.today().isoformat()}',
             '- 数据来源：原型解析', '']

    # 收集所有字段
    all_fields = []
    for page in pages:
        page_name = page['pageName']
        notes = page.get('notes', [])

        for w in page.get('widgets', []):
            w_type = w.get('friendlyType', '') or w.get('type', '')
            if w_type in ('表格', '单元格', '表头', '输入框', '文本框',
                          '下拉列表', '复选框', '单选按钮'):
                field = infer_field_from_widget(w, page_name, notes)
                if field:
                    all_fields.append(field)

        for t in page.get('texts', []):
            if '：' in t or ':' in t:
                field = infer_field_from_label_value(t, page_name, notes)
                if field:
                    all_fields.append(field)

    # 去重
    seen = set()
    unique_fields = []
    for f in all_fields:
        if f['name'] not in seen:
            seen.add(f['name'])
            unique_fields.append(f)

    lines.append('## 2. 字段总览')
    lines.append(f'共定义 {len(unique_fields)} 个字段。')
    lines.append('')
    lines.append('## 3. 字段定义详表')
    lines.append('')

    by_page = {}
    for f in unique_fields:
        by_page.setdefault(f['page'], []).append(f)

    for idx, (page_name, fields) in enumerate(by_page.items(), 1):
        lines.append(f'### 3.{idx} {page_name}')
        lines.append('')
        lines.append('| 字段名 | 中文名 | 类型 | 长度 | 必填 | 默认值 | '
                     '说明 | 所属页面 | 备注 |')
        lines.append('|--------|--------|------|------|------|--------|------|'
                     '----------|------|')
        for f in fields:
            lines.append(
                f'| {f["name"]} | {f["label"]} | {f["type"]} | '
                f'{f.get("length", "-")} | {f.get("required", "否")} | '
                f'{f.get("default", "-")} | {f["desc"]} | {f["page"]} | '
                f'{f.get("note", "-")} |'
            )
        lines.append('')

    # 枚举值定义
    lines.append('## 4. 枚举值定义')
    enum_fields = [f for f in unique_fields if f['type'] == 'enum']
    for f in enum_fields:
        lines.append(f'### {f["name"]}（{f["label"]}）')
        lines.append(f'候选值：{", ".join(f.get("candidates", []))}')
        lines.append('')

    # 数据来源说明
    notes_included = any(p.get('notes') for p in pages)
    lines.append('## 5. 数据来源说明')
    if notes_included:
        lines.append('- 便签/矩形内备注说明已纳入字段定义（"说明"和"备注"列）')
    lines.append('- 字段类型基于原型控件类型推断，长度为推测值，需开发确认')

    # 规范化并校验输出路径，仅允许写入当前工作目录内，防止路径穿越
    base = os.path.realpath(os.getcwd())
    output_path = os.path.realpath(output_path)
    if output_path != base and not output_path.startswith(base + os.sep):
        raise SystemExit(f'输出路径越界，仅允许写入当前工作目录内：{output_path}')
    os.makedirs(os.path.dirname(output_path) or base, exist_ok=True)

    Path(output_path).write_text('\n'.join(lines), encoding='utf-8')


def main():
    if len(sys.argv) < 2:
        print('用法：python3 scripts/generate_data_dict.py <解析JSON> [输出路径]',
              file=sys.stderr)
        sys.exit(1)
    json_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else '数据字典.md'

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    pages = data.get('pages', [])

    generate_data_dictionary_md(pages, output_path)
    print(f'✓ 已生成 {output_path}（{len(pages)} 页面）')


if __name__ == '__main__':
    main()
