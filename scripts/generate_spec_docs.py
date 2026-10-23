#!/usr/bin/env python3
"""从原型解析数据生成开发交付文档。

用法：
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type system-overview
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type detailed-design
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type database-design
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type trial-run-report
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type maintenance-manual
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type operation-manual
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type application-inventory
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type system-parameters
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type training-plan
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type service-plan
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type test-report

输入：parse_axure.py --json 输出的 JSON 文件，或 PRD Markdown 文件。
    也可用 --prd 在原型 JSON 基础上叠加 PRD 内容。
输出：Markdown 文件；未指定输出路径时按文档类型使用默认文件名。
"""
import argparse
import datetime
import html
from collections import Counter
import json
import os
import re
import sys
from pathlib import Path


DOC_TITLES = {
    'system-overview': '系统概要说明书',
    'detailed-design': '详细说明书',
    'database-design': '数据库设计说明书',
    'trial-run-report': '试运行报告',
    'maintenance-manual': '维护手册',
    'operation-manual': '操作手册',
    'application-inventory': '应用软件清单',
    'system-parameters': '系统参数配置说明',
    'training-plan': '培训计划',
    'service-plan': '服务计划',
    'test-report': '功能与性能测试报告',
}

PRD_BASED_DOC_TYPES = {'training-plan', 'service-plan', 'test-report'}

CATEGORY_LABELS = {
    'admin_console': '管理后台',
    'config_page': '配置页面',
    'form_page': '表单页面',
    'list_page': '列表页面',
    'detail_page': '详情页面',
    'flow_diagram': '流程页面',
    'image_composite': '图文页面',
    'dashboard': '数据看板',
    'login_page': '登录页面',
    'mobile_page': '移动页面',
    'modal_dialog': '弹窗页面',
    'unknown': '未分类页面',
}


def category_label(category):
    return CATEGORY_LABELS.get(category or 'unknown', category or '未分类页面')


DEFAULT_OUTPUTS = {
    'system-overview': '系统概要说明书.md',
    'detailed-design': '详细说明书.md',
    'database-design': '数据库设计说明书.md',
    'trial-run-report': '试运行报告.md',
    'maintenance-manual': '维护手册.md',
    'operation-manual': '操作手册.md',
    'application-inventory': '应用软件清单.md',
    'system-parameters': '系统参数配置说明.md',
    'training-plan': '培训计划.md',
    'service-plan': '服务计划.md',
    'test-report': '测试报告.md',
}

DEFAULT_NFR = [
    {'item': '并发量', 'baseline': '按日均 1000 UV 设计', 'condition': '大促/高并发场景'},
    {'item': '数据保留', 'baseline': '永久保留 / 按合规保留 3 年', 'condition': '金融、审计、隐私合规特殊要求'},
    {'item': '删除操作', 'baseline': '软删除 + 操作日志', 'condition': '不可恢复/强审计需求'},
    {'item': '安全加密', 'baseline': '常规传输加密', 'condition': '金融级加密、支付密钥等'},
    {'item': '可用性', 'baseline': '常规（99.9%）', 'condition': '用户明确 SLA 要求'},
]

FIELD_NAME_MAP = {
    'ID': 'id_value',
    '编号': 'code',
    '名称': 'name',
    '配置名称': 'config_name',
    '服务名称': 'service_name',
    '实例名称': 'instance_name',
    '服务配置文件名称': 'service_config_file_name',
    '关联服务名': 'related_service_name',
    '关联服务实例': 'related_service_instance',
    '节点类型': 'node_type',
    '新增服务类型': 'service_type',
    '服务类型': 'service_type',
    '启用状态': 'enabled',
    '状态': 'status',
    '类型': 'type',
    '分类': 'category',
    '级别': 'level',
    '版本': 'version',
    '描述': 'description',
    '说明': 'remark',
    '备注': 'remark',
    '授权说明': 'authorization_note',
    '地址': 'address',
    '邮箱': 'email',
    '手机': 'mobile',
    '手机号': 'mobile',
    '电话': 'phone',
    '部门': 'department',
    '标签': 'tags',
    '排序': 'sort_order',
    '创建时间': 'created_at',
    '更新时间': 'updated_at',
    '立项时间': 'project_started_at',
    '最后发布时间': 'last_published_at',
    '发布时间': 'published_at',
    '触发时间': 'triggered_at',
    '系统类型': 'system_type',
    '系统名称': 'system_name',
    '所在Vlan': 'vlan',
    '服务器IP': 'server_ip',
    'IP': 'ip',
    '环境': 'environment',
    '端口': 'port',
    '用户名': 'username',
    '密码': 'password',
    '协议': 'protocol',
    '路径': 'path',
    '版本号': 'version_no',
}

TABLE_NAME_MAP = {
    '概述': 'overview',
    '概览': 'dashboard',
    '业务': 'business',
    '流程': 'flow',
    '框架': 'framework',
    '实例管理': 'instance',
    '新增节点': 'node',
    '配置中心': 'config_center',
    '发布': 'release',
    '版本管理': 'version',
    '服务配置文件详情': 'service_config_file',
    '模板列表': 'template',
    '认证管理': 'auth',
    '服务配置': 'service_config',
    'Authentication Manager': 'auth_manager',
    '页面 1': 'page_1',
}

CONTROL_TYPE_MAP = {
    '输入框': 'varchar',
    '文本框': 'text',
    '文本域': 'text',
    '下拉列表': 'varchar',
    '下拉框': 'varchar',
    '单选按钮': 'varchar',
    '复选框': 'tinyint',
    '开关': 'tinyint',
    '日期': 'datetime',
    '日期选择器': 'datetime',
    '时间': 'datetime',
    '数字': 'int',
    '数字输入框': 'int',
    '金额': 'decimal(18,2)',
    '文件': 'varchar',
    '图片': 'varchar',
}

TYPE_RULES = [
    (['时间', '日期'], 'datetime'),
    (['金额', '费用', '价格', '余额', '薪资'], 'decimal(18,2)'),
    (['数量', '次数', '人数', '天数', '时长', '比例', '百分比', '排序'], 'int'),
    (['是否', '启用', '有效'], 'tinyint'),
    (['状态', '类型', '分类', '级别', '性别', '渠道', '来源'], 'varchar'),
    (['描述', '说明', '备注', '内容', '地址', '授权'], 'text'),
    (['文件', '图片', '附件'], 'varchar'),
]

ACTION_WORDS = [
    '查询', '搜索', '重置', '清空', '新增', '添加', '创建', '编辑', '修改',
    '删除', '保存', '提交', '发布', '下线', '启用', '禁用', '导入', '导出',
    '下载', '上传', '确认', '取消', '返回', '登录', '注册', '发送', '同步',
]

NOISE_LABELS = {
    '操作', '备注', '说明', '格式正确', '是', '否', '确定', '取消', '返回',
    '登录', '退出', '首页', '查询', '搜索', '重置', '清空', '新增', '编辑',
    '删除', '保存', '提交', '发布', '导出', '导入', '下载', '上传', '更多',
    '全部', '详情', '上一页', '下一页', '上一页/下一页', '共', '条',
    '背景', '概述', '概览', '流程说明', '功能说明', '操作步骤', '注意事项',
    '前提条件', '业务规则', '界面说明', '字段说明', '项目背景', '需求背景',
}

RULE_KEYWORDS = ['必须', '只能', '不可', '不能', '需要', '规则', '有效期',
                 '校验', '限制', '禁止', '至少', '最多', '唯一']


def as_text(value, fallback='待补充'):
    """把任意输入转成适合写入 Markdown 段落的文本。"""
    if value is None or value == '' or value == [] or value == {}:
        return fallback
    if isinstance(value, (list, tuple, set)):
        items = [as_text(item, '') for item in value]
        items = [item for item in items if item]
        return '、'.join(items) if items else fallback
    if isinstance(value, dict):
        items = [f'{k}: {as_text(v, "")}' for k, v in value.items()]
        return '；'.join(items) if items else fallback
    return str(value).strip() or fallback


def cell(value, fallback='-'):
    """表格单元格转义，避免竖线和换行破坏 Markdown 表格。"""
    text = as_text(value, fallback)
    return text.replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def clean_label(text):
    """规范化字段标签，去掉冒号、必填星号与常见提示前缀。"""
    if text is None:
        return ''
    label = str(text).strip()
    label = re.sub(r'\s+', ' ', label)
    label = label.strip('：: *＊')
    label = re.sub(r'^(请输入|请选择|请填写|输入|选择)\s*', '', label)
    return label.strip()


def is_noise_label(label):
    """判断一个文本是否更像按钮/数据值而不是字段标签。"""
    text = clean_label(label)
    if not text or len(text) > 32:
        return True
    if text in NOISE_LABELS:
        return True
    if re.fullmatch(r'[\d\s\-:/.,%+]+', text):
        return True
    if re.fullmatch(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}.*', text):
        return True
    if re.match(r'^\d+[)）.、]', text):
        return True
    if re.fullmatch(r'(.{2,4})\1', text):
        return True
    if text.startswith(('http://', 'https://', 'www.')):
        return True
    if any(token in text for token in ('{{', '}}', '[[', ']]', '→', '->', '=>')):
        return True
    if any(punct in text for punct in ('。', '；', ';')):
        return True
    if any(punct in text for punct in ('，', ',')) and len(text) > 12:
        return True
    if text.endswith(('包括', '如下', '以下')) and len(text) > 8:
        return True
    if any(word in text for word in ('点击', '打开新标签', '跳转至')) and '：' not in text and ':' not in text:
        return True
    return False


def unique(items):
    """按原顺序去重。"""
    seen = set()
    result = []
    for item in items:
        key = str(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def page_texts(page):
    """优先使用去噪文本，保留全量文本作为兜底。"""
    texts = page.get('cleaned_texts') or page.get('texts') or []
    cleaned = []
    for text in texts:
        value = str(text).strip()
        if value:
            cleaned.append(value)
    return unique(cleaned)


def page_widget_labels(page):
    """提取有文字的控件标签。"""
    labels = []
    for widget in page.get('widgets', []):
        label = clean_label(widget.get('label') or widget.get('name') or '')
        if label and not is_noise_label(label):
            labels.append(label)
    return unique(labels)


def page_buttons(page):
    """从控件标签与筛选项里提取操作按钮。"""
    buttons = []
    for label in page_widget_labels(page):
        if any(word in label for word in ACTION_WORDS) and len(label) <= 20:
            buttons.append(label)
    filter_area = page.get('filter_area') or {}
    for action in filter_area.get('filter_actions') or []:
        label = clean_label(action)
        if label:
            buttons.append(label)
    return unique(buttons)


def infer_field_type(label, control_type=''):
    """根据控件类型或字段标签推断数据库类型。"""
    control = str(control_type or '').strip()
    if control and control not in ('待确认', 'unknown', 'None'):
        for key, value in CONTROL_TYPE_MAP.items():
            if key in control:
                return value
    for keywords, field_type in TYPE_RULES:
        if any(keyword in label for keyword in keywords):
            return field_type
    return 'varchar'


def infer_field_name(label, index):
    """推断建议字段名；无法确定时使用 col_N 占位。"""
    label = clean_label(label)
    if label in FIELD_NAME_MAP:
        return FIELD_NAME_MAP[label]
    for key, value in FIELD_NAME_MAP.items():
        if label.endswith(key) and len(label) <= len(key) + 6:
            return value
    ascii_words = re.findall(r'[A-Za-z][A-Za-z0-9_]*', label)
    if ascii_words:
        name = '_'.join(word.lower() for word in ascii_words)
        return name[:60]
    return f'col_{index:02d}'


def normalize_field(raw, index, page_name=''):
    """把 strict_fields / filter_fields 统一成字段定义。"""
    if not isinstance(raw, dict):
        raw = {'label': str(raw)}
    label = clean_label(raw.get('label') or raw.get('name') or '')
    if not label:
        return None
    control = raw.get('type') or raw.get('control_type') or '待确认'
    field_type = infer_field_type(label, control)
    name = raw.get('name') or infer_field_name(label, index)
    length = '-'
    if field_type == 'varchar':
        length = '128'
    elif field_type == 'text':
        length = '-'
    required = as_text(raw.get('required'), '待确认')
    if required not in ('是', '否'):
        required = '待确认'
    default = as_text(raw.get('default_value') or raw.get('default'), '-')
    if default in ('待确认', '待补充'):
        default = '-'
    note_parts = []
    if control and control not in ('待确认', 'unknown'):
        note_parts.append(f'控件类型：{control}')
    if field_type and control in ('待确认', 'unknown', ''):
        note_parts.append('类型由字段标签推断')
    if raw.get('note'):
        note_parts.append(str(raw.get('note')))
    if name in ('created_at', 'updated_at'):
        required = '是'
        default = 'CURRENT_TIMESTAMP'
        note_parts.append('系统字段')
    return {
        'name': name,
        'label': label,
        'type': field_type,
        'length': length,
        'required': required,
        'default': default,
        'description': label,
        'note': '；'.join(note_parts) or '来源：原型页面',
        'page': page_name,
    }


def page_fields(page, limit=40):
    """汇总页面可识别的字段，按标签去重。"""
    page_name = page.get('pageName', '')
    fields = []
    for raw in page.get('strict_fields') or []:
        field = normalize_field(raw, len(fields) + 1, page_name)
        if field and not is_noise_label(field['label']):
            fields.append(field)
    filter_area = page.get('filter_area') or {}
    for raw in filter_area.get('filter_fields') or []:
        field = normalize_field(raw, len(fields) + 1, page_name)
        if field and not is_noise_label(field['label']):
            fields.append(field)
    for column in page.get('table_columns') or []:
        if not isinstance(column, str):
            continue
        field = normalize_field({'label': column}, len(fields) + 1, page_name)
        if field and not is_noise_label(field['label']):
            fields.append(field)
    if not fields:
        for text in page_texts(page):
            match = re.match(r'^([^：:]{2,24})[：:]', text)
            if not match:
                continue
            field = normalize_field({'label': match.group(1)}, len(fields) + 1, page_name)
            if field and not is_noise_label(field['label']):
                fields.append(field)
            if len(fields) >= 20:
                break
    result = []
    seen = set()
    for field in fields:
        key = field['label']
        if key in seen:
            continue
        seen.add(key)
        result.append(field)
        if len(result) >= limit:
            break
    return result


def infer_table_name(page_name, index):
    """推断建议表名，无法确定时使用 module_N。"""
    if page_name in TABLE_NAME_MAP:
        return 't_' + TABLE_NAME_MAP[page_name]
    ascii_words = re.findall(r'[A-Za-z][A-Za-z0-9_]*', page_name)
    if ascii_words:
        slug = '_'.join(word.lower() for word in ascii_words)
    else:
        slug = f'module_{index:02d}'
    return 't_' + slug[:60]


def infer_priority(page):
    """按页面类型推断优先级。"""
    category = page.get('page_category') or 'unknown'
    name = page.get('pageName') or ''
    if category in ('admin_console', 'list_page', 'form_page', 'login_page'):
        return 'P0'
    if any(keyword in name for keyword in ('管理', '配置', '认证', '登录', '新增')):
        return 'P0'
    if category in ('dashboard', 'detail_page', 'config_page'):
        return 'P1'
    return 'P2'


def infer_feature_name(page):
    """按页面类型推断功能名称。"""
    name = page.get('pageName') or '未命名页面'
    category = page.get('page_category') or 'unknown'
    if not re.search(r'[\u4e00-\u9fa5]', name) and re.search(r'[A-Za-z]', name):
        return name
    if name in ('概述', '概览', '业务', '流程', '框架'):
        return f'查看{name}'
    if name == '发布':
        return '发布管理'
    if '新增' in name:
        return name
    if '详情' in name:
        return f'查看{name}'
    if category == 'admin_console':
        return f'查看{name}' if name.endswith('管理') else f'管理{name}'
    if category == 'list_page':
        return f'查看{name}'
    if category == 'config_page':
        return name if '配置' in name else f'配置{name}'
    if category == 'form_page':
        return f'填写{name}'
    if category == 'detail_page':
        return f'查看{name}'
    if category == 'login_page':
        return '用户登录/认证'
    if category == 'dashboard':
        return f'查看{name}'
    if category == 'flow_diagram':
        return f'查看{name}流程'
    return f'查看{name}'


def interaction_steps(page, limit=8, business_only=False):
    """把交互事件整理成可读的流程步骤，过滤原型运行时噪声。"""
    steps = []
    ui_noise = ('设置', '移动 ', '旋转', '显示', '隐藏', '选中状态',
                'bring to front', 'fadewidget', '锚点', '灯箱', 'itemload',
                'selectionchange')
    noise_tokens = ('javascript:', 'localstorage', 'axureprd', '[[axplus',
                    '$.ajax', 'eval(', 'gitee.io', '&quot;', '<div', '<script',
                    '[[', ']]', 'update rows', 'add rows', 'inserted psuedo',
                    'set isexpand', 'set isshow')
    for event in page.get('interactions') or []:
        description = event.get('description') or event.get('action') or ''
        description = html.unescape(str(description))
        description = re.sub(r'<[^>]+>', '', description)
        description = re.sub(r'\s+', ' ', description).strip()
        if len(description) < 3:
            continue
        event_name = event.get('event_type') or event.get('event') or '交互'
        combined = f'{event_name} {description}'.lower()
        if any(token in combined for token in noise_tokens):
            continue
        if business_only and any(token in combined for token in ui_noise):
            continue
        steps.append(f'{event_name}：{description[:160]}')
    for note in page.get('notes') or []:
        text = str(note).strip()
        if text and any(keyword in text for keyword in RULE_KEYWORDS):
            steps.append(f'业务规则：{text[:160]}')
    return unique(steps)[:limit]


def operation_steps(page, limit=6):
    """把交互整理成面向最终用户的操作步骤，过滤 UI 特效与原型跳转噪声。"""
    steps = []
    for raw in interaction_steps(page, limit=limit * 2, business_only=True):
        text = raw
        text = re.sub(r'^(Click时|onClick|MouseOver时|MouseOut时)[：:]\s*', '', text)
        text = re.sub(r'^打开\s*(.+?)\s*在\s*当前窗口$', r'打开「\1」', text)
        text = re.sub(r'^打开\s*(.+?)\s*在\s*新窗口$', r'在新窗口打开「\1」', text)
        text = re.sub(r'^打开\s*(?!「)(.+)$', r'打开「\1」', text)
        text = text.strip('。 ')
        if not text:
            continue
        if text.startswith(('显示', '隐藏', '移动', '旋转', '设置', '选中状态')):
            continue
        if text not in steps:
            steps.append(text)
        if len(steps) >= limit:
            break
    if steps:
        return steps
    buttons = page_buttons(page)
    if buttons:
        return [f'单击「{button}」' for button in buttons[:limit]]
    return []


def infer_acceptance(page, feature_type='main'):
    """生成可测试的验收标准。"""
    name = page.get('pageName') or '页面'
    fields = page_fields(page)
    buttons = page_buttons(page)
    if feature_type == 'filter':
        return [
            f'输入筛选条件后点击查询，「{name}」列表按条件刷新',
            '点击重置后筛选条件清空，列表恢复默认结果',
            '筛选结果为空时展示空状态提示',
        ]
    if feature_type == 'form':
        return [
            f'必填字段为空时禁止提交，并在「{name}」页面给出提示',
            '提交成功后给出成功反馈，并按页面定义返回列表或详情',
            '提交失败时保留已填内容并展示错误信息',
        ]
    criteria = [f'「{name}」页面可正常打开，页面结构完整']
    if fields:
        criteria.append('字段按字段说明展示，必填/默认值/校验规则以确认结果为准')
    if buttons:
        criteria.append(f'点击「{buttons[0]}」可触发对应操作')
    steps = interaction_steps(page, limit=1)
    if steps:
        criteria.append(f'交互「{steps[0][:40]}」按预期执行')
    else:
        criteria.append('页面无交互事件时可正常展示内容')
    return criteria


def strip_markdown_cell(text):
    """去掉单元格两端的空白与 Markdown 强调符号，保留原始内容。"""
    value = str(text or '').strip()
    value = value.strip('`')
    value = re.sub(r'^\*\*(.+?)\*\*$', r'\1', value)
    return value.strip()


def parse_markdown_table(lines):
    """解析 Markdown 表格行，跳过表头分隔行。"""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue
        cells = [strip_markdown_cell(item) for item in stripped.strip('|').split('|')]
        if not cells or all(not item for item in cells):
            continue
        if all(re.fullmatch(r':?-{2,}:?', item or '---') for item in cells):
            continue
        rows.append(cells)
    return rows


def normalize_priority_value(value, fallback='P1'):
    """把 PRD 中的高/中/低或 P0/P1/P2 统一成 P0/P1/P2。"""
    text = str(value or '').strip().upper()
    if text in ('P0', 'P1', 'P2'):
        return text
    if any(word in text for word in ('高', '核心', '紧急', '严重')):
        return 'P0'
    if any(word in text for word in ('中', '重要')):
        return 'P1'
    if any(word in text for word in ('低', '一般')):
        return 'P2'
    return fallback


def parse_prd_markdown(text, source_path=''):
    """从 PRD Markdown 中提取项目名、角色与功能项，作为培训/服务/测试报告输入。"""
    lines = text.splitlines()
    project_name = ''
    version = ''
    roles = []
    for line in lines:
        if not project_name:
            heading = re.match(r'^#\s+(.+?)\s*$', line.strip())
            if heading:
                project_name = re.sub(r'\s*产品需求文档\s*$', '', heading.group(1)).strip()
        if not version:
            match = re.search(r'版本\s*[:：]\s*v?([0-9][0-9A-Za-z.\-]*)', line)
            if match:
                version = match.group(1)
    in_target_users = False
    for line in lines:
        stripped = line.strip()
        if re.match(r'^#{2,4}\s*(目标用户|用户角色|使用角色)\s*$', stripped):
            in_target_users = True
            continue
        if in_target_users and re.match(r'^#{1,4}\s+', stripped):
            in_target_users = False
        if in_target_users:
            match = re.match(r'^[-*+]\s+(.+)$', stripped)
            if match:
                role = re.sub(r'[*`]', '', match.group(1)).strip()
                role = re.split(r'[（(：:]', role)[0].strip()
                if role:
                    roles.append({'name': role, 'description': 'PRD 目标用户'})

    features = []
    current_module = ''
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        module_match = re.match(r'^#{2,4}\s*模块\s*[0-9一二三四五六七八九十]*\s*[：:\-\.]?\s*(.+?)\s*$', line)
        if module_match and not re.match(r'^#{3,5}\s*F-\d+', line, re.IGNORECASE):
            current_module = re.sub(r'[*`]', '', module_match.group(1)).strip()
            index += 1
            continue
        feature_match = re.match(r'^#{3,5}\s*(F-\d+)\s*[：:\-\.]?\s*(.+?)\s*$', line, re.IGNORECASE)
        if not feature_match:
            index += 1
            continue

        feature_id = feature_match.group(1).upper()
        feature_name = re.sub(r'[*`]', '', feature_match.group(2)).strip()
        block = []
        index += 1
        while index < len(lines) and not re.match(r'^#{2,4}\s+\S', lines[index].strip()):
            block.append(lines[index])
            index += 1

        basic = {}
        fields = []
        actions = []
        acceptance = []
        description_lines = []
        section = ''
        for raw in block:
            stripped = raw.strip()
            heading = re.match(r'^\*\*(.+?)\*\*\s*$', stripped)
            if heading:
                section = heading.group(1).strip()
                continue
            if stripped.startswith('|'):
                rows = parse_markdown_table([stripped])
                if not rows:
                    continue
                cells = rows[0]
                key = cells[0]
                if key in ('属性', '字段名', '字段', '按钮/操作', '按钮', '操作'):
                    continue
                if section.startswith('基本信息'):
                    if key in ('所属模块', '优先级', '页面', '操作角色', '角色') and len(cells) > 1:
                        basic[key] = cells[1]
                elif section.startswith(('字段说明', '数据字段')):
                    description = cells[5] if len(cells) > 5 else ''
                    required = cells[2] if len(cells) > 2 else '待确认'
                    default = cells[4] if len(cells) > 4 else '待确认'
                    fields.append({
                        'name': '' if key in ('(待确认)', '待确认') else key,
                        'label': key,
                        'type': cells[1] if len(cells) > 1 else '待确认',
                        'required': required or '待确认',
                        'default': default or '待确认',
                        'description': description or key,
                        'note': '来自 PRD 字段说明',
                        'page': basic.get('页面') or current_module,
                    })
                elif section.startswith(('按钮', '操作逻辑', '按钮/操作逻辑')):
                    if key and key not in actions:
                        actions.append(key)
                continue
            if section == '功能描述' and stripped and not stripped.startswith(('>', '-', '```', '!')):
                description_lines.append(stripped)
            match = re.match(r'^[-*+]\s*\[[ xX]\]\s*(.+)$', stripped)
            if match:
                acceptance.append(re.sub(r'[*`]', '', match.group(1)).strip())

        name = feature_name
        module = basic.get('所属模块') or current_module or '未分组'
        feature = {
            'id': feature_id,
            'module': module,
            'name': name,
            'description': ' '.join(description_lines).strip() or f'实现「{name}」功能。',
            'priority': normalize_priority_value(basic.get('优先级')),
            'fields': fields,
            'actions': actions,
            'flow': [],
            'business_rules': [],
            'acceptance': acceptance or [f'「{name}」按 PRD 定义完成并可验证'],
            'page': basic.get('页面') or module,
            'role': basic.get('操作角色') or basic.get('角色') or '',
        }
        features.append(feature)

    if not features:
        raise ValueError('未能从 PRD 中解析到功能项（需要形如「#### F-001 功能名称」的标题）')

    grouped = {}
    for feature in features:
        grouped.setdefault(feature['module'], []).append(feature['name'])
    pages = []
    for module, names in grouped.items():
        pages.append({
            'pageName': module,
            'page_category': 'unknown',
            'texts': names,
            'widgets': {},
            'interactions': [],
            'notes': [],
            'strict_fields': [],
            'ambiguous_fields': [],
            'filter_area': {},
        })

    if not roles:
        roles = [{'name': '系统用户', 'description': 'PRD 未明确角色，待业务方确认'}]
    return {
        'project_name': project_name or '未命名项目',
        'doc_version': version,
        'prd_path': source_path,
        'tool': 'PRD 文档',
        'root_path': source_path or '未提供',
        'source_kind': 'prd',
        'pages': pages,
        'prd_features': features,
        'prd_modules': [{'name': module, 'features': [f for f in features if f['module'] == module]}
                        for module in grouped],
        'prd_roles': roles,
    }


def merge_prd_context(data, prd_data):
    """把 PRD 解析结果叠加到原型 JSON 数据上，不覆盖原型页面。"""
    merged = dict(data)
    merged['prd_features'] = prd_data.get('prd_features') or []
    merged['prd_modules'] = prd_data.get('prd_modules') or []
    merged['prd_roles'] = prd_data.get('prd_roles') or []
    merged['prd_path'] = prd_data.get('prd_path') or ''
    if not merged.get('project_name'):
        merged['project_name'] = prd_data.get('project_name')
    return merged


def build_features(pages):
    """把页面转换成功能项。"""
    features = []
    number = 1
    for page in pages:
        page_name = page.get('pageName') or '未命名页面'
        category = page.get('page_category') or 'unknown'
        fields = page_fields(page)
        buttons = page_buttons(page)
        notes = [str(note).strip() for note in (page.get('notes') or []) if str(note).strip()]
        rules = [note for note in notes if any(keyword in note for keyword in RULE_KEYWORDS)]
        features.append({
            'id': f'F-{number:03d}',
            'module': page_name,
            'name': infer_feature_name(page),
            'description': f'承载「{page_name}」页面的主要业务操作（页面类型：{category_label(category)}）。',
            'priority': infer_priority(page),
            'fields': fields,
            'actions': buttons,
            'flow': interaction_steps(page),
            'business_rules': rules,
            'acceptance': infer_acceptance(page),
            'page': page_name,
        })
        number += 1

        filter_area = page.get('filter_area') or {}
        if filter_area.get('has_filter'):
            filter_fields = [
                normalize_field(raw, idx + 1, page_name)
                for idx, raw in enumerate(filter_area.get('filter_fields') or [])
            ]
            filter_fields = [field for field in filter_fields if field and not is_noise_label(field['label'])]
            actions = [clean_label(action) for action in filter_area.get('filter_actions') or [] if clean_label(action)]
            features.append({
                'id': f'F-{number:03d}',
                'module': page_name,
                'name': f'筛选查询{page_name}',
                'description': f'按条件筛选并查询「{page_name}」页面的数据。',
                'priority': 'P1',
                'fields': filter_fields,
                'actions': actions,
                'flow': [f'输入筛选条件：{as_text([field["label"] for field in filter_fields])}',
                         f'点击操作：{as_text(actions)}', '刷新列表并展示结果'],
                'business_rules': [],
                'acceptance': infer_acceptance(page, feature_type='filter'),
                'page': page_name,
            })
            number += 1

        input_fields = [field for field in fields if field['type'] in ('varchar', 'text', 'int', 'decimal(18,2)', 'datetime', 'tinyint')]
        if category == 'form_page' or (len(input_fields) >= 3 and category in ('admin_console', 'config_page')):
            form_name = f'填写并提交{page_name}'
            if not re.search(r'[\u4e00-\u9fa5]', page_name):
                form_name = '填写并提交表单'
            features.append({
                'id': f'F-{number:03d}',
                'module': page_name,
                'name': form_name,
                'description': f'在「{page_name}」页面填写表单并提交保存。',
                'priority': 'P1',
                'fields': input_fields,
                'actions': buttons,
                'flow': [
                    f'填写字段：{as_text([field["label"] for field in input_fields[:5]])}',
                    '提交表单并进行必填/格式校验',
                    '校验通过后保存，失败时保留输入并提示',
                ],
                'business_rules': rules,
                'acceptance': infer_acceptance(page, feature_type='form'),
                'page': page_name,
            })
            number += 1
    return features


def build_modules(pages, features):
    """按页面分组功能项。"""
    modules = []
    for page in pages:
        page_name = page.get('pageName') or '未命名页面'
        page_features = [feature for feature in features if feature['module'] == page_name]
        modules.append({
            'name': page_name,
            'category': page.get('page_category') or 'unknown',
            'page': page,
            'features': page_features,
        })
    return modules


def build_modules_from_features(features, pages=None):
    """按功能项的 module 字段分组，兼容 PRD 输入。"""
    page_categories = {
        page.get('pageName'): page.get('page_category') or 'unknown'
        for page in (pages or [])
    }
    modules = []
    index_by_name = {}
    for feature in features:
        name = feature.get('module') or '未分组'
        if name not in index_by_name:
            index_by_name[name] = len(modules)
            modules.append({
                'name': name,
                'category': page_categories.get(name, 'unknown'),
                'page': None,
                'features': [],
            })
        modules[index_by_name[name]]['features'].append(feature)
    return modules


def doc_features(data, pages):
    """优先使用 PRD 功能项，否则回退到原型页面推断。"""
    return data.get('prd_features') or build_features(pages)


def doc_modules(data, pages, features):
    return build_modules_from_features(features, pages)


def doc_roles(data, pages):
    return data.get('prd_roles') or infer_roles(pages)


def build_entities(pages):
    """把有字段的页面推断成建议实体。"""
    entities = []
    skipped = []
    used_tables = set()
    for index, page in enumerate(pages, 1):
        page_name = page.get('pageName') or f'页面 {index}'
        fields = page_fields(page)
        category = page.get('page_category') or 'unknown'
        if not fields:
            skipped.append(page_name)
            continue
        table_name = infer_table_name(page_name, index)
        while table_name in used_tables:
            table_name += '_2'
        used_tables.add(table_name)
        entity_fields = [{
            'name': 'id',
            'label': '主键',
            'type': 'bigint',
            'length': '-',
            'required': '是',
            'default': '-',
            'description': '主键（设计约定）',
            'note': '系统字段',
            'page': page_name,
        }]
        seen_names = {'id'}
        for field in fields:
            name = field['name']
            while name in seen_names:
                name += '_2'
            seen_names.add(name)
            normalized = {**field, 'name': name}
            if name in ('created_at', 'updated_at'):
                note = normalized.get('note') or ''
                if '系统字段' not in note:
                    note = f'{note}；系统字段' if note else '系统字段'
                normalized.update({
                    'required': '是',
                    'default': 'CURRENT_TIMESTAMP',
                    'note': note,
                })
            entity_fields.append(normalized)
        for name, label, description in (
            ('created_at', '创建时间', '创建时间（设计约定）'),
            ('updated_at', '更新时间', '更新时间（设计约定）'),
        ):
            if name not in seen_names:
                seen_names.add(name)
                entity_fields.append({
                    'name': name,
                    'label': label,
                    'type': 'datetime',
                    'length': '-',
                    'required': '是',
                    'default': 'CURRENT_TIMESTAMP',
                    'description': description,
                    'note': '系统字段',
                    'page': page_name,
                })
        entity_fields = (
            [field for field in entity_fields if field['name'] == 'id']
            + [field for field in entity_fields if field['name'] not in ('id', 'created_at', 'updated_at')]
            + [field for name in ('created_at', 'updated_at')
               for field in entity_fields if field['name'] == name]
        )
        indexes = [{
            'name': f'PRIMARY',
            'type': '主键',
            'fields': ['id'],
            'description': '主键索引',
        }]
        for field in entity_fields:
            if field['name'] in ('created_at', 'updated_at'):
                continue
            if field['name'] in ('status', 'type', 'category', 'enabled'):
                indexes.append({
                    'name': f'idx_{table_name[2:]}_{field["name"]}',
                    'type': '普通索引',
                    'fields': [field['name']],
                    'description': '按该字段筛选（建议，待确认）',
                })
            elif field['name'] in ('code', 'name') and field['name'] != 'name':
                indexes.append({
                    'name': f'uk_{table_name[2:]}_{field["name"]}',
                    'type': '唯一索引',
                    'fields': [field['name']],
                    'description': '业务唯一性（建议，待确认）',
                })
        entities.append({
            'name': page_name,
            'table_name': table_name,
            'description': f'由「{page_name}」页面字段推断（页面类型：{category_label(category)}）',
            'primary_key': 'id',
            'fields': entity_fields,
            'indexes': indexes,
            'relations': [],
            'page': page,
        })
    return entities, skipped


def infer_relations(entities):
    """基于页面命名推断实体关系。"""
    relations = []
    for entity in entities:
        name = entity['name']
        for suffix in ('详情', '新增', '编辑'):
            if suffix not in name:
                continue
            base = name.replace(suffix, '').strip()
            candidates = [other for other in entities if other is not entity]
            best = None
            for other in candidates:
                other_name = other['name']
                if other_name == base or (base and (base in other_name or other_name in base)):
                    best = other
                    break
            if best:
                relation = {
                    'from': best['table_name'],
                    'to': entity['table_name'],
                    'type': '1:N',
                    'description': f'一个{best["name"]}对应多个{name}（基于页面命名推断）',
                }
                relations.append(relation)
                entity['relations'].append(relation['description'])
    return unique(relations)


def infer_roles(pages):
    """按页面类型推断用户角色。"""
    roles = []
    mapping = {
        'admin_console': ('管理员', '管理后台数据的查询、维护与发布'),
        'config_page': ('配置管理员', '维护系统配置与参数'),
        'list_page': ('业务用户', '查询与浏览业务数据'),
        'detail_page': ('业务用户', '查看业务详情'),
        'form_page': ('业务用户', '填写并提交业务表单'),
        'login_page': ('登录用户', '完成身份认证后访问系统'),
        'mobile_page': ('移动端用户', '在移动端完成业务操作'),
        'dashboard': ('管理者', '查看数据看板与经营指标'),
        'flow_diagram': ('业务用户', '查看业务流程与拓扑关系'),
    }
    for page in pages:
        category = page.get('page_category') or 'unknown'
        if category in mapping:
            roles.append(mapping[category])
    if not roles:
        roles.append(('系统用户', '使用系统完成业务操作'))
    result = []
    seen = set()
    for name, duty in roles:
        if name in seen:
            continue
        seen.add(name)
        result.append({'name': name, 'description': duty})
    return result


def infer_interfaces(entities, pages):
    """按页面类型推断建议接口。"""
    interfaces = []
    category_by_page = {page.get('pageName'): page.get('page_category') for page in pages}
    for entity in entities:
        page_name = entity['name']
        category = category_by_page.get(page_name, 'unknown')
        resource = entity['table_name'][2:]
        if category == 'login_page':
            interfaces.append({
                'name': '用户登录', 'type': 'HTTP', 'provider': '后端服务',
                'caller': '前端页面', 'description': f'POST /api/{resource}/login（建议，待确认）',
            })
            continue
        if category in ('admin_console', 'list_page'):
            interfaces.append({
                'name': f'查询{page_name}', 'type': 'HTTP', 'provider': '后端服务',
                'caller': '前端页面', 'description': f'GET /api/{resource}（建议，待确认）',
            })
        if category in ('detail_page', 'config_page'):
            interfaces.append({
                'name': f'读取{page_name}', 'type': 'HTTP', 'provider': '后端服务',
                'caller': '前端页面', 'description': f'GET /api/{resource}/{{id}}（建议，待确认）',
            })
        if category in ('form_page', 'admin_console', 'config_page'):
            interfaces.append({
                'name': f'保存{page_name}', 'type': 'HTTP', 'provider': '后端服务',
                'caller': '前端页面', 'description': f'POST/PUT /api/{resource}（建议，待确认）',
            })
        if '发布' in page_name:
            publish_name = page_name if page_name != '发布' else '发布操作'
            interfaces.append({
                'name': publish_name, 'type': 'HTTP', 'provider': '后端服务',
                'caller': '前端页面', 'description': f'POST /api/{resource}/publish（建议，待确认）',
            })
    deduped = []
    seen = set()
    for item in interfaces:
        key = (item['name'], item['description'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:15]


def render_table(headers, rows, empty_row=None):
    """渲染简单 Markdown 表格；rows 为二维列表。"""
    lines = ['| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join(['------'] * len(headers)) + '|']
    if rows:
        for row in rows:
            lines.append('| ' + ' | '.join(cell(value) for value in row) + ' |')
    else:
        fallback = empty_row or ['待补充'] + ['-'] * (len(headers) - 1)
        lines.append('| ' + ' | '.join(cell(value) for value in fallback) + ' |')
    return lines


def build_parameter_candidates(pages):
    """从配置类页面字段推断候选业务参数。"""
    params = []
    seen = set()
    for page in pages:
        category = page.get('page_category') or 'unknown'
        if category not in ('config_page', 'admin_console'):
            continue
        page_name = page.get('pageName') or '未命名页面'
        for field in page_fields(page):
            if field['name'] in ('id', 'created_at', 'updated_at'):
                continue
            name = f'biz.{field["name"]}'
            while name in seen:
                name += '_2'
            seen.add(name)
            params.append({
                'name': name,
                'page': page_name,
                'description': field['label'],
                'type': field['type'],
                'default': field['default'],
                'required': field['required'],
                'note': '配置页面字段推断，是否作为系统参数待确认',
            })
            if len(params) >= 40:
                return params
    return params


def build_inventory_baseline():
    """应用软件清单的通用基线条目，均需运维确认。"""
    return [
        ('Web 前端应用', '业务应用', '待确认', '页面展示、表单与交互', '待确认', '自研/待确认', '原型页面推断'),
        ('后端应用服务', '业务应用', '待确认', '业务编排、接口与事务处理', '待确认', '自研/待确认', '原型交互推断'),
        ('数据库', '基础软件', '待确认（建议 MySQL 8.0）', '业务数据持久化', '待确认', '开源/商业待确认', '通用基线建议'),
        ('缓存服务', '中间件', '待确认（如 Redis）', '会话、热点数据缓存', '待确认', '开源/商业待确认', '通用基线建议'),
        ('Web 服务器/反向代理', '中间件', '待确认（如 Nginx）', '静态资源、反向代理与 TLS', '待确认', '开源/商业待确认', '通用基线建议'),
        ('消息队列', '中间件', '待确认', '异步任务与系统解耦', '待确认', '开源/商业待确认', '按需启用'),
        ('日志与监控', '运维工具', '待确认', '日志采集、指标监控与告警', '待确认', '开源/商业待确认', '通用基线建议'),
        ('操作系统', '基础软件', '待确认（建议 Linux）', '应用与中间件运行底座', '待确认', '商业/开源待确认', '通用基线建议'),
        ('容器与编排', '运维工具', '待确认', '应用打包、部署与弹性伸缩', '待确认', '开源/商业待确认', '按需启用'),
        ('CI/CD 工具', '运维工具', '待确认', '构建、测试与发布流水线', '待确认', '开源/商业待确认', '按需启用'),
    ]


def build_scenario_rows(modules):
    """按模块名称/类型推断常见业务场景。"""
    def names(predicate, limit=6):
        result = []
        for module in modules:
            if predicate(module):
                result.append(module['name'])
        return result[:limit]

    query = names(lambda m: m['category'] in ('list_page', 'admin_console', 'dashboard'))
    edit = names(lambda m: m['category'] in ('form_page', 'config_page', 'detail_page'))
    config = names(lambda m: '配置' in m['name'] or m['category'] == 'config_page')
    publish = names(lambda m: any(word in m['name'] for word in ('发布', '版本')))
    auth = names(lambda m: '认证' in m['name'] or '登录' in m['name'])
    rows = [
        ('查询与浏览', query, '进入列表/管理页面，输入筛选条件，查看查询结果', '列表按条件刷新，无数据时展示空态'),
        ('新增与编辑', edit, '进入表单/配置页面，填写字段并提交', '校验通过后保存，失败时保留输入并提示'),
        ('配置与发布', unique(config + publish), '维护配置内容，提交发布并查看版本状态', '发布成功后可查询版本与生效状态'),
        ('认证与权限', auth, '进入认证/登录相关页面，完成身份校验', '认证成功进入系统，失败提示原因'),
    ]
    filtered = [row for row in rows if row[1]]
    if filtered:
        return filtered
    fallback = [module['name'] for module in modules][:6]
    if not fallback:
        return []
    return [('核心业务操作', fallback, '按角色完成查询、录入、提交与结果核对', '操作成功并得到明确反馈')]


def render_trial_run_report(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = build_features(pages)
    modules = build_modules(pages, features)
    interfaces = infer_interfaces(entities, pages)
    priority_counts = Counter(feature['priority'] for feature in features)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['trial-run-report'])]
    lines.extend(render_intro(project_name, DOC_TITLES['trial-run-report'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 试运行概述', '', '### 2.1 系统简介', '',
                  f'本系统由原型内容推断，覆盖 {len(pages)} 个页面、{len(modules)} 个模块、{len(features)} 个功能项。'
                  '原型未提供真实试运行记录，本文档中的执行结果、指标与结论均需在试运行完成后补充。', '',
                  '### 2.2 试运行目标', '',
                  '- 验证页面主功能、筛选查询、表单提交与关键业务流程',
                  '- 验证系统间接口、权限控制、数据完整性与异常处理',
                  '- 验证系统在目标环境下的性能、稳定性与可运维性',
                  '- 收集用户反馈与缺陷，形成上线整改清单', '',
                  '### 2.3 试运行范围', ''])
    lines.extend(render_module_table(modules))
    lines.extend(['', '### 2.4 试运行环境', ''])
    lines.extend(render_table(
        ['环境项', '配置要求', '实际值', '确认状态'],
        [('应用地址', '试运行环境访问地址', '待确认', '待确认'),
         ('应用版本', '本次试运行版本号', '待确认', '待确认'),
         ('数据库', '类型、版本、实例', '待确认', '待确认'),
         ('中间件', '缓存、消息队列、Web 服务器', '待确认', '待确认'),
         ('操作系统', '服务器操作系统与版本', '待确认', '待确认'),
         ('网络', '内外网访问与端口策略', '待确认', '待确认')]))
    lines.extend(['', '### 2.5 试运行时间与人员', ''])
    lines.extend(render_table(
        ['阶段', '计划时间', '参与角色', '主要职责'],
        [('环境准备', '待确认', '运维/开发', '部署、配置、连通性检查'),
         ('功能试运行', '待确认', '业务/测试', '按功能清单执行验证并记录问题'),
         ('问题整改', '待确认', '开发/测试', '修复、回归并更新问题状态'),
         ('试运行总结', '待确认', '项目组', '汇总指标、风险与上线建议')]))

    lines.extend(['', '## 3. 试运行准备', '', '### 3.1 环境与部署检查', ''])
    lines.extend(render_table(
        ['检查项', '检查要求', '检查结果', '备注'],
        [('应用部署', '前后端服务已部署，版本与试运行计划一致', '待检查', '-'),
         ('数据库', '库表已初始化，连接正常，账号权限最小化', '待检查', '-'),
         ('配置项', '环境地址、参数、密钥已按环境配置', '待检查', '-'),
         ('网络与端口', '客户端可访问，依赖系统连通', '待检查', '-'),
         ('日志与监控', '日志可查，关键指标已接入监控', '待检查', '-'),
         ('备份与回滚', '已完成基线备份，回滚包可用', '待检查', '-')]))
    lines.extend(['', '### 3.2 测试数据准备', ''])
    lines.extend(render_table(
        ['数据类别', '数据来源', '建议数量', '脱敏要求', '准备状态'],
        [('基础字典', '生产导出/手工构造', '按需', '不含敏感信息', '待确认'),
         ('业务主数据', '生产脱敏数据', '覆盖正常/边界场景', '姓名、手机号、地址脱敏', '待确认'),
         ('异常数据', '手工构造', '覆盖空值、超长、非法格式', '不含真实个人信息', '待确认')]))
    lines.extend(['', '### 3.3 人员与培训', ''])
    lines.extend(render_table(
        ['角色', '培训内容', '培训方式', '确认状态'],
        [('业务用户', '页面操作、业务规则、问题反馈', '集中培训/演示', '待确认'),
         ('测试人员', '用例执行、缺陷记录、回归验证', '文档+实操', '待确认'),
         ('运维人员', '部署、巡检、日志、回滚', '文档+演练', '待确认')]))
    lines.extend(['', '### 3.4 准入检查清单', '',
                  '- [ ] 试运行环境与生产环境的关键配置差异已确认',
                  '- [ ] 试运行版本、数据库脚本与回滚包已归档',
                  '- [ ] 测试数据已脱敏并完成导入',
                  '- [ ] 参与人员、时间窗口与沟通机制已确认',
                  '- [ ] 问题记录模板与责任人已明确', ''])

    lines.extend(['## 4. 试运行执行', '', '### 4.1 功能验证', ''])
    feature_rows = []
    for feature in features[:40]:
        feature_rows.append((feature['id'], feature['module'], feature['name'],
                             feature['priority'], '待执行', '-'))
    lines.extend(render_table(['编号', '模块', '功能', '优先级', '验证结果', '问题编号'], feature_rows))
    lines.extend(['', '### 4.2 业务流程验证', ''])
    flow_rows = []
    for page in pages:
        steps = interaction_steps(page, limit=4, business_only=True)
        if steps:
            flow_rows.append((page.get('pageName') or '未命名页面', as_text(steps), '待执行', '-'))
    lines.extend(render_table(['流程/页面', '关键步骤', '验证结果', '问题编号'], flow_rows,
                              empty_row=['待补充', '原型未提取到业务流程', '待执行', '-']))
    lines.extend(['', '### 4.3 接口验证', ''])
    interface_rows = [(item['name'], item['type'], item['description'], '待执行', '-')
                      for item in interfaces]
    lines.extend(render_table(['接口名称', '类型', '说明', '验证结果', '问题编号'], interface_rows))
    lines.extend(['', '### 4.4 非功能验证', ''])
    nfr_rows = [(item['item'], item['baseline'], '待执行', '待确认') for item in DEFAULT_NFR]
    lines.extend(render_table(['验证项', '目标基线', '验证结果', '备注'], nfr_rows))

    lines.extend(['', '## 5. 试运行结果', '', '### 5.1 功能结果汇总', ''])
    lines.extend(render_table(
        ['统计项', '数量', '说明'],
        [('功能项总数', len(features), '来自原型页面推断'),
         ('P0 功能', priority_counts.get('P0', 0), '核心功能'),
         ('P1 功能', priority_counts.get('P1', 0), '重要功能'),
         ('P2 功能', priority_counts.get('P2', 0), '一般功能'),
         ('已验证功能', '待确认', '试运行完成后填写'),
         ('通过率', '待确认', '通过数/已验证数')]))
    lines.extend(['', '### 5.2 缺陷与问题清单', ''])
    lines.extend(render_table(
        ['编号', '模块', '问题描述', '严重级别', '状态', '责任人', '计划修复时间'],
        [('待记录', '待确认', '原型未提供缺陷记录，试运行后补充', '-', '待记录', '待确认', '待确认')]))
    lines.extend(['', '### 5.3 运行指标', ''])
    lines.extend(render_table(
        ['指标', '目标值', '实测值', '结论'],
        [('页面平均响应时间', '待确认', '待确认', '待确认'),
         ('核心接口成功率', '待确认', '待确认', '待确认'),
         ('系统可用性', '待确认', '待确认', '待确认'),
         ('错误日志数量', '待确认', '待确认', '待确认'),
         ('用户操作完成率', '待确认', '待确认', '待确认')]))
    lines.extend(['', '### 5.4 业务反馈', '',
                  '- 业务用户对功能完整性的反馈：待收集',
                  '- 业务用户对操作便捷性的反馈：待收集',
                  '- 业务规则与例外场景的补充说明：待收集', ''])

    lines.extend(['## 6. 问题整改与上线建议', '', '### 6.1 整改计划', ''])
    lines.extend(render_table(
        ['问题编号', '整改措施', '责任人', '完成时间', '验证方式'],
        [('待记录', '待确认', '待确认', '待确认', '回归测试')]))
    lines.extend(['', '### 6.2 风险评估', ''])
    lines.extend(render_table(
        ['风险项', '影响', '概率', '应对措施'],
        [('核心功能未通过', '影响上线范围', '待确认', '修复后回归，必要时缩小上线范围'),
         ('性能不达标', '影响用户体验', '待确认', '扩容、优化或增加缓存'),
         ('数据迁移异常', '影响数据一致性', '待确认', '演练迁移与回滚，保留基线备份'),
         ('权限配置错误', '影响数据安全', '待确认', '上线前复核角色与权限矩阵')]))
    lines.extend(['', '### 6.3 上线建议', '',
                  '试运行结论需基于真实执行记录形成。当前原型未提供试运行数据，建议在完成功能、接口、非功能验证并关闭阻塞级问题后再决定是否上线。', ''])

    lines.extend(['## 7. 试运行结论', '', '### 7.1 结论', '',
                  '待试运行完成后填写：是否满足上线条件、遗留问题及限制条件。', '',
                  '### 7.2 后续工作', '',
                  '- 完成缺陷修复与回归验证',
                  '- 更新操作手册与维护手册',
                  '- 完成上线审批、备份与回滚演练', ''])
    lines.extend(render_appendix('trial-run-report', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_maintenance_manual(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = build_features(pages)
    modules = build_modules(pages, features)
    interfaces = infer_interfaces(entities, pages)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['maintenance-manual'])]
    lines.extend(render_intro(project_name, DOC_TITLES['maintenance-manual'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 系统概述', '', '### 2.1 系统架构', '',
                  '- **架构风格**: 待确认（原型仅体现页面与交互）',
                  '- **应用组成**: 前端页面、后端服务、数据库与中间件（具体以部署为准）',
                  '- **部署方式**: 待确认（物理机/虚拟机/容器）', '',
                  '### 2.2 部署拓扑', '',
                  '待运维提供：网络区域、应用节点、数据库节点、负载均衡与备份节点。', '',
                  '### 2.3 依赖组件', ''])
    lines.extend(render_table(
        ['组件', '用途', '版本', '部署位置', '备注'],
        [('Web 前端', '页面展示与交互', '待确认', '待确认', '-'),
         ('后端服务', '业务接口与任务', '待确认', '待确认', '-'),
         ('数据库', '业务数据存储', '待确认', '待确认', '-'),
         ('缓存/消息队列', '会话、异步任务', '待确认', '待确认', '按需'),
         ('日志/监控', '可观测性', '待确认', '待确认', '-')]))
    lines.extend(['', '### 2.4 运行环境', ''])
    lines.extend(render_table(
        ['环境', '地址', '版本', '用途', '负责人'],
        [('开发', '待确认', '待确认', '开发自测', '待确认'),
         ('测试', '待确认', '待确认', '测试/UAT', '待确认'),
         ('生产', '待确认', '待确认', '正式运行', '待确认')]))

    lines.extend(['', '## 3. 维护组织与职责', '', '### 3.1 角色职责', ''])
    lines.extend(render_table(
        ['角色', '主要职责', '联系方式'],
        [('业务负责人', '确认业务规则、上线范围与问题优先级', '待确认'),
         ('应用运维', '部署、巡检、监控、发布与故障处理', '待确认'),
         ('开发人员', '缺陷修复、版本发布与技术支持', '待确认'),
         ('DBA', '数据库备份、性能优化与数据恢复', '待确认'),
         ('安全负责人', '权限审计、漏洞修复与安全事件响应', '待确认')]))
    lines.extend(['', '### 3.2 值守与响应', '',
                  '- 服务时间：待确认（7×24 或 5×8）',
                  '- 告警响应时限：P1 15 分钟内、P2 30 分钟内、P3 4 小时内、P4 次工作日（默认基线，待确认）',
                  '- 升级路径：一线运维 → 应用负责人 → 开发负责人 → 项目负责人', '',
                  '### 3.3 升级路径', ''])
    lines.extend(render_table(
        ['级别', '触发条件', '处理人', '升级时限'],
        [('L1', '常规咨询、单页面异常', '一线运维', '待确认'),
         ('L2', '功能故障、接口异常', '应用运维/开发', '待确认'),
         ('L3', '数据库、网络、安全事件', 'DBA/安全/架构', '待确认')]))

    lines.extend(['', '## 4. 日常维护', '', '### 4.1 巡检计划', ''])
    lines.extend(render_table(
        ['周期', '巡检项', '检查方法', '正常标准'],
        [('每日', '应用进程、页面可用性、错误日志', '监控/日志平台', '无持续错误，页面可访问'),
         ('每日', '数据库连接、慢查询、磁盘空间', '数据库监控', '连接正常，空间充足'),
         ('每周', '备份结果、证书有效期、账号变更', '备份平台/台账', '备份成功，证书未临期'),
         ('每月', '容量趋势、性能基线、补丁情况', '监控报表/漏洞扫描', '无异常增长，无高危漏洞'),
         ('每季', '恢复演练、权限复核、应急预案', '演练/审计', '演练通过，权限无冗余')]))
    lines.extend(['', '### 4.2 日志管理', '',
                  '- 日志类型：应用日志、访问日志、错误日志、审计日志',
                  '- 日志级别：生产默认 INFO，排障时临时调整并限期恢复',
                  '- 保留期限：不少于 180 天（默认基线，待确认）',
                  '- 清理策略：按保留期限归档/清理，清理前确认备份完成', '',
                  '### 4.3 备份与恢复', ''])
    lines.extend(render_table(
        ['对象', '备份频率', '保留期限', '恢复目标', '演练要求'],
        [('数据库全量', '每日', '待确认', '待确认', '每季一次'),
         ('数据库增量', '待确认', '待确认', '待确认', '每季一次'),
         ('应用配置', '每次变更', '待确认', '待确认', '每次发布前'),
         ('文件/附件', '待确认', '待确认', '待确认', '每季一次')]))
    lines.extend(['', '### 4.4 监控与告警', ''])
    lines.extend(render_table(
        ['监控对象', '指标', '建议阈值', '告警方式'],
        [('应用', '可用性、错误率、响应时间', '待确认', '短信/邮件/IM'),
         ('数据库', '连接数、慢查询、磁盘使用率', '待确认', '短信/邮件/IM'),
         ('中间件', '队列积压、缓存命中率', '待确认', '短信/邮件/IM'),
         ('主机', 'CPU、内存、磁盘、网络', '待确认', '短信/邮件/IM')]))
    lines.extend(['', '### 4.5 账号与权限', '',
                  '- 账号申请、变更、离岗回收均需审批留痕',
                  '- 生产账号按最小权限授予，禁止共享账号',
                  '- 每季度复核角色与权限，清理长期未使用账号', '',
                  '### 4.6 补丁与版本', '',
                  '- 建立版本台账，记录版本号、发布内容、发布时间与回滚包',
                  '- 高危漏洞按安全要求限期修复，修复前评估影响范围',
                  '- 版本升级前在测试环境验证，生产发布按变更流程执行', ''])

    lines.extend(['## 5. 故障处理', '', '### 5.1 故障分级', ''])
    lines.extend(render_table(
        ['级别', '定义', '示例', '响应要求'],
        [('P1', '核心业务不可用或数据严重受损', '系统无法登录、数据丢失', '立即响应，优先恢复'),
         ('P2', '主要功能不可用但有替代方案', '发布失败、部分页面不可用', '30 分钟内响应'),
         ('P3', '一般功能异常或体验问题', '提示错误、样式异常', '4 小时内响应'),
         ('P4', '咨询、建议或低影响问题', '操作咨询、文案问题', '次工作日处理')]))
    lines.extend(['', '### 5.2 常见故障处理', ''])
    lines.extend(render_table(
        ['现象', '可能原因', '排查步骤', '处理建议'],
        [('页面无法访问', '服务停止、网络、代理配置', '检查进程、端口、网关与 DNS', '重启服务/修复网络/回滚版本'),
         ('登录失败', '账号锁定、认证服务异常、时钟偏差', '检查账号状态、认证日志、系统时间', '解锁账号/恢复认证服务/校时'),
         ('接口超时', '慢查询、下游依赖、连接池耗尽', '查看调用链、数据库慢查询、线程池', '优化 SQL/扩容/限流降级'),
         ('配置不生效', '缓存未刷新、配置源错误、发布未完成', '核对配置源、缓存与发布记录', '刷新缓存/重新发布/回滚配置'),
         ('发布失败', '脚本错误、依赖缺失、权限不足', '查看发布日志与数据库迁移记录', '修复后重试/回滚到上一版本'),
         ('数据不一致', '并发写入、事务异常、同步失败', '核对业务日志、事务与同步任务', '停止写入/修复数据/补做同步')]))
    lines.extend(['', '### 5.3 应急处置流程', '',
                  '1. 发现与记录：确认现象、影响范围与发生时间',
                  '2. 上报与分级：按故障级别通知责任人',
                  '3. 止损：限流、降级、切换或回滚，优先恢复业务',
                  '4. 定位：结合日志、监控、调用链与变更记录排查',
                  '5. 恢复：验证核心功能与数据一致性',
                  '6. 复盘：输出根因、改进项与责任人', '',
                  '### 5.4 恢复与回滚', '',
                  '- 回滚前确认数据库变更是否可逆，必要时先备份',
                  '- 应用回滚与数据库回滚按发布方案顺序执行',
                  '- 回滚后验证登录、核心查询、提交与接口连通性', ''])

    lines.extend(['## 6. 变更与发布', '', '### 6.1 变更流程', '',
                  '变更申请 → 影响评估 → 审批 → 测试验证 → 发布实施 → 观察与关闭', '',
                  '### 6.2 发布检查清单', '',
                  '- [ ] 发布包、配置与数据库脚本已归档',
                  '- [ ] 回滚包与回滚步骤已确认',
                  '- [ ] 发布窗口与通知已发出',
                  '- [ ] 监控、日志与告警已就绪',
                  '- [ ] 发布后验证项与责任人已明确', '',
                  '### 6.3 回滚方案', '',
                  '- 触发条件：核心功能不可用、错误率持续升高、数据异常',
                  '- 回滚步骤：停止发布 → 恢复上一版本 → 回滚数据库（如需要）→ 验证 → 通知',
                  '- 回滚后保留现场日志与数据快照，供根因分析', ''])

    lines.extend(['## 7. 安全与合规', '', '### 7.1 账号与权限', '',
                  '生产权限按角色最小化授予，敏感操作双人复核，离岗即时回收。', '',
                  '### 7.2 数据安全', '',
                  '敏感数据加密存储与传输，导出审批，测试环境使用脱敏数据。', '',
                  '### 7.3 审计与合规', '',
                  '关键操作、权限变更与数据导出记录审计日志，按合规要求保留。', ''])

    lines.extend(['## 8. 应急预案与演练', '', '### 8.1 应急场景', ''])
    lines.extend(render_table(
        ['场景', '影响', '应急措施', '恢复目标'],
        [('数据库故障', '业务不可用', '切换备库/恢复备份', '待确认'),
         ('应用节点故障', '部分或全部不可用', '负载摘除/重启/切换节点', '待确认'),
         ('网络中断', '访问失败', '切换线路/启用备用入口', '待确认'),
         ('安全事件', '数据或服务风险', '隔离、取证、修复、通知', '待确认')]))
    lines.extend(['', '### 8.2 演练计划', '',
                  '- 每半年至少一次恢复演练，覆盖数据库、应用与配置回滚',
                  '- 演练后更新预案、联系人与检查清单',
                  '- 记录演练时间、参与人、问题与改进项', ''])
    lines.extend(render_appendix('maintenance-manual', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_operation_manual(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = build_features(pages)
    modules = build_modules(pages, features)
    roles = infer_roles(pages)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['operation-manual'])]
    lines.extend(render_intro(project_name, DOC_TITLES['operation-manual'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 系统访问', '', '### 2.1 访问地址', '',
                  '- 访问地址：待确认（由实施团队提供）',
                  '- 支持浏览器：待确认（建议 Chrome/Edge 最新版）',
                  '- 网络要求：待确认（内网/VPN/公网）', '',
                  '### 2.2 登录步骤', '',
                  '1. 打开浏览器，输入系统访问地址。',
                  '2. 输入账号与密码，完成验证码/二次验证（如启用）。',
                  '3. 单击“登录”，进入系统首页。',
                  '4. 首次登录按提示修改初始密码。', '',
                  '### 2.3 首页与导航', ''])
    lines.extend(render_module_table(modules))
    lines.extend(['', '### 2.4 退出登录', '',
                  '单击右上角用户菜单，选择“退出登录”；在公共电脑使用后必须退出并关闭浏览器。', ''])

    lines.extend(['## 3. 角色与权限', ''])
    lines.extend(render_roles_table(roles))
    lines.extend(['', '> 原型未提供按钮级权限矩阵，具体可见范围与操作权限以系统配置为准。', ''])

    lines.extend(['## 4. 功能操作', ''])
    for index, module in enumerate(modules, 1):
        page = module['page']
        lines.append(f'### 4.{index} {module["name"]}')
        lines.append('')
        lines.append(f'**功能说明**：{cell(category_label(module["category"]))}，包含 '
                     f'{len(module["features"])} 个功能项：{as_text([feature["name"] for feature in module["features"]])}。')
        lines.append('')
        lines.append('**操作步骤**')
        lines.append('')
        steps = operation_steps(page, limit=6)
        if steps:
            for step_index, step in enumerate(steps, 1):
                lines.append(f'{step_index}. {step}')
        else:
            lines.append(f'1. 进入「{module["name"]}」页面。')
            lines.append('2. 按页面提示选择查询条件或填写表单。')
            lines.append('3. 单击页面主操作按钮完成操作。')
        lines.append('')
        fields = []
        seen = set()
        for feature in module['features']:
            for field in feature.get('fields') or []:
                if field['name'] in seen:
                    continue
                seen.add(field['name'])
                fields.append(field)
        if not fields:
            fields = page_fields(page)
        if fields:
            lines.append('**字段说明**')
            lines.append('')
            lines.extend(render_table(
                ['字段', '类型', '必填', '默认值', '说明'],
                [(field['label'], field['type'], field['required'], field['default'], field['description'])
                 for field in fields[:15]]))
            lines.append('')
        lines.append('**结果与异常**')
        lines.append('')
        lines.append('- 成功：页面提示操作成功，列表/详情数据同步刷新。')
        lines.append('- 失败：保留当前输入并提示原因；按提示修正后重试。')
        lines.append('- 无权限：提示无访问权限，请联系管理员分配角色。')
        lines.append('')

    lines.extend(['## 5. 常见业务场景', ''])
    lines.extend(render_table(
        ['场景', '涉及模块', '操作步骤', '预期结果'],
        build_scenario_rows(modules)))
    lines.extend(['', '## 6. 常见问题', ''])
    lines.extend(render_table(
        ['问题', '可能原因', '处理方式'],
        [('无法登录', '账号密码错误、账号锁定、网络不通', '核对账号、联系管理员解锁、检查网络'),
         ('页面空白/加载失败', '缓存、浏览器兼容、服务异常', '刷新/清缓存/更换浏览器，仍失败联系运维'),
         ('查询无数据', '筛选条件过严、数据未同步', '放宽条件、清空筛选、确认数据状态'),
         ('保存失败', '必填项缺失、格式错误、无权限', '按提示修正、检查权限'),
         ('操作按钮不可见', '角色权限不足', '联系管理员分配权限')]))
    lines.extend(['', '## 7. 使用说明', '', '### 7.1 术语', '',
                  '- 模块：系统导航中的一个业务页面或功能分组。',
                  '- 字段：页面中需要查看或填写的数据项。',
                  '- 待确认：原型未体现、需业务方或实施团队确认的内容。', '',
                  '### 7.2 使用建议', '',
                  '- 操作前确认当前环境与账号权限。',
                  '- 批量操作前先小范围验证。',
                  '- 遇到异常先记录页面、时间、操作步骤与提示信息，再联系支持人员。', ''])
    lines.extend(render_appendix('operation-manual', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_application_inventory(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = build_features(pages)
    modules = build_modules(pages, features)
    interfaces = infer_interfaces(entities, pages)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['application-inventory'])]
    lines.extend(render_intro(project_name, DOC_TITLES['application-inventory'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 清单说明', '', '### 2.1 编制目的', '',
                  '用于盘点系统涉及的业务应用、基础软件、中间件与运维工具，支撑部署实施、版本管理、许可采购与资产审计。', '',
                  '### 2.2 统计口径', '',
                  '- 业务应用：为本次项目开发或配置的应用系统。',
                  '- 基础软件：操作系统、数据库、运行时等底座。',
                  '- 中间件/运维工具：缓存、消息队列、Web 服务器、监控、CI/CD 等。',
                  '- 版本与许可：原型未体现的条目统一标“待确认”，不得视为已采购。', '',
                  '### 2.3 数据来源与维护', '',
                  '- 业务模块来自原型页面推断；基础软件为通用基线建议。',
                  '- 清单责任人：待确认；建议每季度复核一次。', ''])

    lines.extend(['## 3. 应用软件清单', '', '### 3.1 基础软件与中间件', ''])
    inventory_rows = []
    for index, row in enumerate(build_inventory_baseline(), 1):
        name, category, ver, purpose, deploy, license_type, source = row
        inventory_rows.append((index, name, category, ver, purpose, deploy, license_type, source,
                               '原型未体现，需运维确认'))
    lines.extend(render_table(
        ['序号', '软件名称', '类别', '版本', '用途', '部署位置', '许可类型', '来源', '备注'],
        inventory_rows))
    lines.extend(['', '### 3.2 业务应用模块', ''])
    module_rows = []
    for index, module in enumerate(modules, 1):
        module_rows.append((index, module['name'], category_label(module['category']),
                            len(module['features']),
                            as_text([feature['name'] for feature in module['features'][:4]]),
                            '待确认', '由原型页面推断'))
    lines.extend(render_table(
        ['序号', '应用/模块', '页面类型', '功能项数', '主要功能', '部署单元', '备注'],
        module_rows))
    lines.extend(['', '### 3.3 接口与外部依赖', '',
                  '> 以下接口由页面操作推断，不等同于已确认的外部系统依赖。', ''])
    dependency_rows = [(item['name'], item['type'], item['description'], '待确认')
                       for item in interfaces[:12]]
    lines.extend(render_table(['依赖/接口', '类型', '说明', '确认状态'], dependency_rows,
                              empty_row=['待确认', '-', '原型未提供外部系统依赖', '待确认']))

    lines.extend(['', '## 4. 版本与许可管理', '', '### 4.1 版本管理', '',
                  '- 建立软件台账，记录名称、版本、部署位置、责任人与更新时间。',
                  '- 升级前评估兼容性、许可与回滚方案，禁止直接覆盖生产版本。',
                  '- 关注开源组件 EOL 与安全公告，按风险等级安排升级。', '',
                  '### 4.2 许可管理', ''])
    lines.extend(render_table(
        ['许可类型', '适用软件', '管理要求', '到期/续期'],
        [('自研', '业务应用', '内部版本与源码管理', '不适用'),
         ('开源', '数据库/中间件/工具', '保留许可证与版权声明，遵守开源协议', '关注版本生命周期'),
         ('商业', '操作系统/商业中间件', '登记授权数量、到期时间与供应商', '到期前续期'),
         ('云服务', '托管数据库/监控等', '登记订阅、配额与账单责任人', '按订阅周期续期')]))

    lines.extend(['', '## 5. 部署与依赖关系', '', '### 5.1 部署单元', ''])
    lines.extend(render_table(
        ['部署单元', '包含组件', '部署位置', '说明'],
        [('前端', 'Web 前端应用', '待确认', '静态资源与页面入口'),
         ('应用服务', '后端应用服务', '待确认', '业务接口与后台任务'),
         ('数据层', '数据库/缓存', '待确认', '持久化与缓存'),
         ('运维层', '日志/监控/CI/CD', '待确认', '可观测性与发布')]))
    lines.extend(['', '### 5.2 依赖关系', '',
                  '- 前端依赖后端接口与静态资源服务。',
                  '- 后端依赖数据库、缓存与消息队列（如启用）。',
                  '- 日志、监控与备份依赖运维基础设施。',
                  '- 具体端口、域名与网络策略待运维补充。', ''])
    lines.extend(render_appendix('application-inventory', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_system_parameters(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    params = build_parameter_candidates(pages)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['system-parameters'])]
    lines.extend(render_intro(project_name, DOC_TITLES['system-parameters'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 配置概述', '', '### 2.1 配置来源', '',
                  '- 配置文件、环境变量、启动参数、数据库配置表或配置中心。',
                  '- 具体来源与加载顺序待开发/运维确认。', '',
                  '### 2.2 优先级', '',
                  '启动参数 > 环境变量 > 配置中心 > 配置文件 > 代码默认值（默认基线，待确认）。', '',
                  '### 2.3 生效方式', ''])
    lines.extend(render_table(
        ['生效方式', '适用参数', '操作要求'],
        [('重启生效', '端口、数据库连接、线程池等启动参数', '变更后重启并验证'),
         ('热加载', '日志级别、部分业务开关', '确认框架支持后执行'),
         ('下次请求生效', '缓存、分页、超时等', '观察后续请求与监控'),
         ('重新发布', '构建期参数、前端配置', '按发布流程执行')]))
    lines.extend(['', '### 2.4 环境划分', '',
                  '开发、测试、预生产、生产环境使用独立配置，禁止跨环境复用密钥与生产数据。', ''])

    lines.extend(['## 3. 参数清单', '', '### 3.1 系统基础参数', ''])
    baseline = [
        ('system.name', '系统', '系统名称', project_name, '字符串', '重启', '否', '展示与日志标识'),
        ('system.env', '系统', '运行环境', 'prod', 'dev/test/prod', '重启', '否', '环境隔离'),
        ('system.timezone', '系统', '时区', 'Asia/Shanghai', 'IANA 时区', '重启', '否', '时间字段统一'),
        ('security.session-timeout', '安全', '会话超时（分钟）', '30', '5-1440', '下次请求', '否', '无操作自动退出'),
        ('security.password-min-length', '安全', '密码最小长度', '8', '8-64', '下次请求', '否', '密码策略'),
        ('security.login-fail-lock', '安全', '登录失败锁定次数', '5', '3-10', '下次请求', '否', '防暴力破解'),
        ('upload.max-size', '文件', '单文件上传上限（MB）', '20', '1-1024', '下次请求', '否', '附件上传限制'),
        ('page.default-size', '页面', '列表默认分页大小', '20', '10-200', '下次请求', '否', '列表查询'),
        ('log.level', '日志', '日志级别', 'INFO', 'DEBUG/INFO/WARN/ERROR', '热加载', '否', '排障与性能平衡'),
        ('log.retention-days', '日志', '日志保留天数', '180', '30-3650', '重启', '否', '审计与合规'),
        ('backup.retention-days', '备份', '备份保留天数', '30', '7-3650', '重启', '否', '恢复窗口'),
        ('api.timeout-ms', '接口', '接口超时（毫秒）', '5000', '1000-60000', '重启', '否', '防止长时间阻塞'),
        ('feature.publish-approval', '业务', '发布是否需要审批', 'true', 'true/false', '下次请求', '否', '发布流程控制'),
    ]
    lines.extend(render_table(
        ['参数名', '分类', '说明', '默认值', '取值范围', '生效方式', '敏感', '备注'],
        baseline))
    lines.extend(['', '### 3.2 业务参数（配置页面字段推断）', ''])
    parameter_rows = [(item['name'], item['page'], item['description'], item['type'],
                       item['default'], item['required'], item['note'])
                      for item in params]
    lines.extend(render_table(
        ['参数名', '所属页面', '说明', '类型', '默认值', '必填', '备注'],
        parameter_rows,
        empty_row=['待补充', '-', '原型未识别到配置页面字段', '-', '-', '待确认', '-']))
    lines.extend(['', '> 以上业务参数由配置类页面字段推断，是否作为系统参数、参数键名与取值范围需业务方确认。', ''])

    lines.extend(['### 3.3 敏感参数', ''])
    lines.extend(render_table(
        ['参数/配置', '敏感原因', '存储要求', '脱敏要求', '轮换要求'],
        [('数据库密码', '可直接访问业务数据', '密钥管理/加密配置', '日志禁止输出', '按安全策略定期轮换'),
         ('接口密钥/Token', '可调用外部系统', '密钥管理/加密配置', '日志与前端禁止暴露', '按有效期轮换'),
         ('文件存储凭证', '可读写附件', '密钥管理', '日志脱敏', '按安全策略轮换'),
         ('管理员初始密码', '可获取高权限', '首次登录强制修改', '禁止明文传递', '首次登录即失效')]))

    lines.extend(['', '## 4. 配置管理流程', '', '### 4.1 变更申请', '',
                  '填写参数名、当前值、目标值、变更原因、影响范围与回滚值。', '',
                  '### 4.2 审批', '',
                  '普通参数由应用负责人审批；安全、权限、发布相关参数需安全/业务负责人复核。', '',
                  '### 4.3 发布与生效', '',
                  '按生效方式执行变更，变更后验证核心功能与监控指标，并记录操作人与时间。', '',
                  '### 4.4 回滚', '',
                  '保留变更前配置快照；异常时按快照回滚并验证，禁止无记录直接修改生产配置。', '',
                  '### 4.5 审计', '',
                  '配置变更记录操作人、时间、参数、前后值与审批单号，审计日志不可篡改。', ''])

    lines.extend(['## 5. 环境差异', ''])
    lines.extend(render_table(
        ['参数', '开发', '测试', '生产', '说明'],
        [('system.env', 'dev', 'test', 'prod', '环境标识'),
         ('log.level', 'DEBUG', 'INFO', 'INFO', '生产避免 DEBUG'),
         ('security.session-timeout', '待确认', '待确认', '30', '按安全要求调整'),
         ('upload.max-size', '待确认', '待确认', '20', '按业务需要调整'),
         ('feature.publish-approval', 'false', 'true', 'true', '生产必须审批')]))

    lines.extend(['', '## 6. 校验与故障处理', ''])
    lines.extend(render_table(
        ['现象', '可能原因', '处理方式'],
        [('配置不生效', '来源优先级错误、缓存未刷新、未重启', '核对来源与优先级，刷新缓存或重启'),
         ('启动失败', '必填参数缺失、格式错误、端口占用', '查看启动日志，校验参数与端口'),
         ('上传失败', '超过大小限制、存储不可用', '调整 upload.max-size 或检查存储'),
         ('登录频繁失效', '会话超时过短、Cookie/时钟异常', '调整超时，检查客户端与服务器时间'),
         ('日志过多', '日志级别过低、异常循环', '调整 log.level，修复异常来源')]))
    lines.extend(['', '> 参数默认值与取值范围为通用基线，必须结合框架、部署环境与安全要求确认后使用。', ''])
    lines.extend(render_appendix('system-parameters', data, pages, entities, skipped, version))
    return '\n'.join(lines)



def render_training_plan(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = doc_features(data, pages)
    modules = doc_modules(data, pages, features)
    roles = doc_roles(data, pages)
    priority_counts = Counter(feature['priority'] for feature in features)
    core_features = [feature for feature in features if feature['priority'] == 'P0']
    focus_modules = [
        module for module in modules
        if '配置' in module['name'] or module['category'] in ('config_page', 'admin_console')
    ]
    source = 'PRD' if data.get('prd_features') else '原型解析数据'
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['training-plan'])]
    is_prd = bool(data.get('prd_features'))
    intro_pages = [{'pageName': module['name']} for module in modules] if is_prd else pages
    lines.extend(render_intro(project_name, DOC_TITLES['training-plan'], intro_pages, data.get('tool'),
                              data.get('root_path'), 'PRD' if is_prd else '原型',
                              '模块' if is_prd else '页面'))

    lines.extend(['## 2. 培训概述', '', '### 2.1 培训目标', '',
                  f'本培训计划基于{source}整理，覆盖 {len(modules)} 个模块、{len(features)} 个功能项，'
                  '目标是让不同角色在系统上线前掌握本职范围内的页面操作、业务规则与异常处理。', '',
                  '- 使业务用户能够独立完成日常查询、录入、提交与结果核对',
                  '- 使配置/管理人员掌握配置维护、权限边界与变更注意事项',
                  '- 使运维与支持人员了解常见问题定位、反馈路径与升级机制',
                  '- 通过考核确认培训效果，形成可追溯的培训记录', '',
                  '### 2.2 培训对象', ''])
    role_rows = []
    for role in roles:
        related = '、'.join(module['name'] for module in modules[:6]) or '全部模块'
        role_rows.append((role['name'], role.get('description') or 'PRD 目标用户',
                          related, '待确认'))
    lines.extend(render_table(['角色', '职责', '主要涉及模块', '人数'], role_rows))
    lines.extend(['', '### 2.3 培训范围', ''])
    lines.extend(render_module_table(modules))
    lines.extend(['', '### 2.4 培训前提与约束', ''])
    lines.extend(render_table(
        ['前提项', '要求', '确认状态'],
        [('培训环境', '可访问的测试/预生产环境，数据与生产隔离', '待确认'),
         ('账号权限', '按角色准备演示账号与最小权限', '待确认'),
         ('培训教材', '操作手册、功能清单、演示脚本', '待确认'),
         ('培训时间', '避开业务高峰，分批次组织', '待确认'),
         ('培训数据', '使用脱敏或构造数据，禁止使用真实敏感数据', '待确认')]))

    lines.extend(['', '## 3. 培训需求分析', '', '### 3.1 角色能力矩阵', ''])
    matrix_rows = []
    for role in roles:
        duties = role.get('description') or '按角色权限使用系统'
        matrix_rows.append((role['name'], duties,
                            '、'.join(feature['name'] for feature in core_features[:5]) or '核心业务操作',
                            '待确认'))
    lines.extend(render_table(['角色', '能力要求', '重点功能', '建议课时'], matrix_rows))
    lines.extend(['', '### 3.2 模块培训需求', ''])
    module_rows = []
    for module in modules:
        module_features = module['features']
        names = '、'.join(feature['name'] for feature in module_features[:4])
        if len(module_features) > 4:
            names += ' 等'
        hours = max(1, min(4, len(module_features)))
        module_rows.append((module['name'], len(module_features), names,
                            '讲解+演示+实操', f'建议 {hours} 学时（待确认）'))
    lines.extend(render_table(['模块', '功能项数', '核心功能', '培训方式', '建议课时'], module_rows))
    lines.extend(['', '### 3.3 培训重点与难点', ''])
    lines.append('- **高频核心功能**：' + (as_text([feature['name'] for feature in core_features[:8]])
                                     if core_features else '待确认'))
    lines.append('- **配置与权限**：' + (as_text([module['name'] for module in focus_modules[:8]])
                                    if focus_modules else '原型/PRD 未识别到独立配置页面，按实际权限配置讲解'))
    lines.append('- **易错业务规则**：必填校验、状态流转、审批/发布条件，按 PRD 与操作手册逐项演示')
    lines.append('- **异常处理**：查询无结果、提交失败、权限不足、数据冲突时的提示与处理方式')
    lines.append('- **数据安全**：脱敏要求、导出限制、账号共享与操作留痕要求')
    lines.append('')

    lines.extend(['## 4. 培训内容与课程安排', '', '### 4.1 课程大纲', ''])
    course_rows = []
    for index, module in enumerate(modules[:20], 1):
        names = '、'.join(feature['name'] for feature in module['features'][:5])
        course_rows.append((f'TR-{index:02d}', f'{module["name"]}功能培训', module['name'],
                            names or '模块整体操作', '待确认', '讲解+演示+实操'))
    lines.extend(render_table(['课程编号', '课程名称', '覆盖模块', '培训要点', '课时', '培训方式'],
                              course_rows))
    if len(modules) > 20:
        lines.extend(['', f'> 模块数量超过 20 个，其余 {len(modules) - 20} 个模块按模块清单补充课程。'])
    lines.extend(['', '### 4.2 分角色课程组合', ''])
    combo_rows = []
    for role in roles:
        combo_rows.append((role['name'], '全部模块课程（按权限裁剪）',
                           '配置/权限/安全相关课程', '实操考核'))
    lines.extend(render_table(['角色', '必修课程', '选修课程', '考核方式'], combo_rows))
    lines.extend(['', '### 4.3 操作演练场景', ''])
    scenario_rows = []
    for row in build_scenario_rows(modules):
        scenario_rows.append((row[0], as_text(row[1]), row[2], row[3]))
    lines.extend(render_table(['演练场景', '涉及模块', '操作要点', '预期结果'], scenario_rows,
                              empty_row=['待补充', '原型/PRD 未提取到可演练场景', '待确认', '待确认']))

    lines.extend(['', '## 5. 培训组织与实施', '', '### 5.1 培训方式', ''])
    lines.extend(render_table(
        ['方式', '适用对象', '说明'],
        [('集中授课', '业务用户/管理员', '统一讲解系统范围、流程与规则'),
         ('在线演示', '分散办公人员', '录屏或直播，便于回看'),
         ('实操演练', '关键用户', '在测试环境按场景完成操作'),
         ('一对一辅导', '配置/管理人员', '针对权限、配置与发布流程'),
         ('文档自学', '全员', '操作手册、常见问题与视频教材')]))
    lines.extend(['', '### 5.2 讲师与教材', ''])
    lines.extend(render_table(
        ['项目', '要求', '责任人', '确认状态'],
        [('讲师', '熟悉业务规则与系统操作，建议由产品/实施/关键用户担任', '待确认', '待确认'),
         ('教材', '操作手册、功能清单、演示脚本、练习题', '待确认', '待确认'),
         ('演示环境', '与培训内容一致的测试环境', '待确认', '待确认'),
         ('培训记录', '签到表、课件版本、考核结果', '待确认', '待确认')]))
    lines.extend(['', '### 5.3 培训环境与数据', ''])
    lines.extend(render_table(
        ['项目', '要求', '确认状态'],
        [('应用地址', '培训环境访问地址', '待确认'),
         ('账号', '按角色准备演示账号', '待确认'),
         ('数据', '脱敏/构造数据，覆盖正常与异常场景', '待确认'),
         ('网络', '培训现场网络与访问权限', '待确认')]))
    lines.extend(['', '### 5.4 培训日程', ''])
    lines.extend(render_table(
        ['阶段', '计划时间', '培训对象', '主要内容', '讲师'],
        [('培训准备', '待确认', '项目组', '环境、账号、教材与演示脚本准备', '待确认'),
         ('管理员培训', '待确认', '管理员/配置人员', '配置、权限、发布与审计', '待确认'),
         ('业务用户培训', '待确认', '业务用户', '核心功能、操作流程与常见问题', '待确认'),
         ('实操与答疑', '待确认', '关键用户', '按场景演练并收集问题', '待确认'),
         ('考核与总结', '待确认', '全体培训对象', '考核、补训与培训总结', '待确认')]))

    lines.extend(['', '## 6. 考核与效果评估', '', '### 6.1 考核方式', ''])
    lines.extend(render_table(
        ['考核方式', '适用对象', '内容', '合格标准'],
        [('实操考核', '业务用户/管理员', '按岗位完成指定业务场景', '待确认'),
         ('笔试/问卷', '全员', '功能范围、业务规则、安全要求', '待确认'),
         ('现场问答', '关键用户', '异常处理与升级路径', '待确认')]))
    lines.extend(['', '### 6.2 合格标准', ''])
    lines.append('- 能独立完成本角色 100% 的核心操作场景（具体场景待确认）')
    lines.append('- 能说明关键字段含义、必填要求与常见校验提示')
    lines.append('- 能按流程反馈问题，不绕过权限或审批直接操作')
    lines.append('- 考核未通过者安排补训与补考，记录留档')
    lines.extend(['', '### 6.3 效果评估指标', ''])
    lines.extend(render_table(
        ['指标', '目标值', '数据来源', '备注'],
        [('培训覆盖率', '待确认', '签到表', '应培训人数/实际培训人数'),
         ('考核通过率', '待确认', '考核记录', '首次通过率与补考通过率'),
         ('操作问题数量', '待确认', '支持工单/答疑记录', '上线后两周内的操作类问题'),
         ('用户满意度', '待确认', '培训反馈问卷', '内容、讲师、组织安排'),
         ('关键用户覆盖率', '待确认', '培训记录', '每个业务班组至少 1 名关键用户')]))

    lines.extend(['', '## 7. 培训保障与风险', '', '### 7.1 组织保障', ''])
    lines.append('- 明确培训负责人、讲师、关键用户与考勤记录人')
    lines.append('- 培训前完成环境、账号、教材与演示数据检查')
    lines.append('- 培训后归档课件、签到表、考核结果与问题清单')
    lines.extend(['', '### 7.2 风险与应对', ''])
    lines.extend(render_table(
        ['风险项', '影响', '应对措施'],
        [('培训时间不足', '用户不熟悉操作，上线后问题集中', '分批次培训，保留补训与录屏'),
         ('环境不可用', '演示中断，影响培训效果', '提前检查并准备备用环境/截图'),
         ('角色覆盖不全', '部分用户未掌握操作', '按角色清单核对签到与权限'),
         ('业务规则变化', '培训内容与实际不一致', '以最新 PRD 和操作手册为准，培训前复核'),
         ('培训数据不合规', '泄露真实敏感信息', '统一使用脱敏或构造数据')]))
    lines.append('')
    lines.extend(render_appendix('training-plan', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_service_plan(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = doc_features(data, pages)
    modules = doc_modules(data, pages, features)
    roles = doc_roles(data, pages)
    priority_counts = Counter(feature['priority'] for feature in features)
    source = 'PRD' if data.get('prd_features') else '原型解析数据'
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['service-plan'])]
    is_prd = bool(data.get('prd_features'))
    intro_pages = [{'pageName': module['name']} for module in modules] if is_prd else pages
    lines.extend(render_intro(project_name, DOC_TITLES['service-plan'], intro_pages, data.get('tool'),
                              data.get('root_path'), 'PRD' if is_prd else '原型',
                              '模块' if is_prd else '页面'))

    lines.extend(['## 2. 服务概述', '', '### 2.1 服务目标', '',
                  f'本服务计划基于{source}整理，覆盖 {len(modules)} 个模块、{len(features)} 个功能项，'
                  '用于明确系统上线后的服务范围、服务级别、组织职责与工作流程。', '',
                  '- 保障系统稳定运行，业务问题能够得到及时受理与闭环',
                  '- 明确服务边界、响应时限、升级路径与考核方式',
                  '- 规范变更、发布、巡检、备份与应急处理',
                  '- 形成可追溯的服务记录与持续改进机制', '',
                  '### 2.2 服务对象', ''])
    service_roles = [role['name'] for role in roles]
    lines.append('- 业务用户：' + (as_text(service_roles) if service_roles else '待确认'))
    lines.append('- 系统管理员/配置人员：日常配置维护、权限管理与发布操作')
    lines.append('- 运维与技术支持：部署、巡检、监控、故障处理与变更实施')
    lines.append('- 外部依赖方：云平台、网络、第三方接口供应商（如涉及，待确认）')
    lines.extend(['', '### 2.3 服务范围', ''])
    lines.extend(render_module_table(modules))
    lines.extend(['', '### 2.4 服务边界', ''])
    lines.extend(render_table(
        ['范围类型', '内容', '说明'],
        [('包含', '应用功能支持、权限配置、日常巡检、故障受理、变更发布', '以合同/服务协议约定为准'),
         ('包含', '接口连通性排查、日志查询、备份与恢复配合', '依赖方责任边界内配合'),
         ('不包含', '用户终端与网络维护、第三方系统内部故障', '由相应责任方处理'),
         ('不包含', '超出约定范围的新功能开发', '按变更或新增需求流程处理')]))

    lines.extend(['', '## 3. 服务组织与职责', '', '### 3.1 服务团队角色', ''])
    lines.extend(render_table(
        ['服务角色', '主要职责', '建议人数', '责任人'],
        [('服务经理', '服务统筹、SLA 考核、重大事件协调与客户沟通', '待确认', '待确认'),
         ('一线支持', '受理、分类、常规问题处理与进度反馈', '待确认', '待确认'),
         ('二线支持', '业务规则、配置与数据分析类问题处理', '待确认', '待确认'),
         ('研发支持', '缺陷修复、代码级排查与版本发布', '待确认', '待确认'),
         ('运维支持', '部署、巡检、监控、备份恢复与资源调整', '待确认', '待确认'),
         ('DBA', '数据库性能、备份恢复与数据修复', '待确认', '待确认'),
         ('安全负责人', '权限审计、安全事件响应与合规检查', '待确认', '待确认'),
         ('供应商', '云资源、网络、第三方接口支持', '待确认', '待确认')]))
    lines.extend(['', '### 3.2 职责分工', ''])
    lines.extend(render_table(
        ['事项', '负责(R)', '审批(A)', '协作(C)', '知会(I)'],
        [('服务受理与分派', '一线支持', '服务经理', '二线支持', '业务方'),
         ('重大故障处理', '二线/研发', '服务经理', '运维/供应商', '业务方'),
         ('变更与发布', '研发/运维', '服务经理', '测试/业务', '一线支持'),
         ('权限与账号', '系统管理员', '安全负责人', '一线支持', '业务方'),
         ('数据恢复', 'DBA/运维', '服务经理', '研发', '业务方'),
         ('服务报告', '服务经理', '项目负责人', '各支持组', '业务方')]))
    lines.extend(['', '### 3.3 沟通与升级机制', ''])
    lines.extend(render_table(
        ['级别', '触发条件', '升级对象', '时限'],
        [('一线处理', '常规咨询、操作指导、一般问题', '一线支持', '按 SLA'),
         ('二线升级', '一线无法定位或涉及配置/数据', '二线支持', '待确认'),
         ('研发升级', '疑似缺陷、接口异常、性能问题', '研发支持', '待确认'),
         ('管理升级', '重大故障、SLA 即将超时、跨方协调', '服务经理/项目负责人', '待确认')]))

    lines.extend(['', '## 4. 服务内容', '', '### 4.1 实施与上线服务', ''])
    lines.append('- 环境部署、参数配置、数据库初始化与连通性验证')
    lines.append('- 上线前检查、版本归档、备份与回滚演练')
    lines.append('- 上线窗口值守与上线后观察')
    lines.extend(['', '### 4.2 培训与推广服务', ''])
    lines.append('- 按《培训计划》组织角色培训、关键用户培训与补训')
    lines.append('- 提供操作手册、常见问题与演示材料')
    lines.extend(['', '### 4.3 日常运维服务', ''])
    lines.extend(render_table(
        ['服务项', '内容', '频次', '责任方'],
        [('系统巡检', '应用、数据库、中间件、磁盘、证书、日志', '待确认', '运维'),
         ('监控告警', '可用性、响应时间、错误率、资源使用率', '持续', '运维'),
         ('备份检查', '数据库与文件备份完整性、可恢复性', '待确认', 'DBA/运维'),
         ('账号权限复核', '账号有效性、权限最小化、离职清理', '待确认', '系统管理员'),
         ('日志与审计', '操作日志、安全日志、异常日志检查', '待确认', '运维/安全')]))
    lines.extend(['', '### 4.4 故障响应与恢复', ''])
    lines.extend(render_table(
        ['故障级别', '典型场景', '响应要求', '恢复要求', '升级要求'],
        [('P0 重大', '系统不可用、核心数据异常、严重安全事件', '待确认（建议 15 分钟内）',
          '待确认（建议 4 小时内）', '立即上报服务经理与项目负责人'),
         ('P1 高', '核心功能不可用或大面积受影响', '待确认（建议 30 分钟内）',
          '待确认（建议 8 小时内）', '1 小时内升级二线/研发'),
         ('P2 中', '一般功能异常，有替代方案', '待确认（建议 2 小时内）',
          '待确认（建议 3 个工作日内）', '按需升级'),
         ('P3 低', '咨询、建议、界面问题', '待确认（建议 1 个工作日内）',
          '纳入版本计划', '无需升级')]))
    lines.extend(['', '### 4.5 变更与发布服务', ''])
    lines.extend(render_table(
        ['环节', '要求', '产出'],
        [('变更申请', '说明变更内容、影响范围、回滚方案与验证方式', '变更单'),
         ('变更评审', '按风险等级由服务经理/业务/安全审批', '评审记录'),
         ('变更实施', '在约定窗口执行，禁止无记录直接修改生产', '实施记录'),
         ('变更验证', '验证核心功能、接口与监控指标', '验证记录'),
         ('变更回滚', '异常时按预案回滚并复盘', '回滚记录/复盘报告')]))
    lines.extend(['', '### 4.6 数据与安全服务', ''])
    lines.append('- 数据备份、恢复演练与数据导出审批')
    lines.append('- 账号权限申请、变更、复核与离职回收')
    lines.append('- 安全事件受理、止损、取证与上报')
    lines.append('- 日志脱敏、敏感数据访问审计与合规检查')
    lines.extend(['', '### 4.7 巡检与健康检查', ''])
    lines.extend(render_table(
        ['检查项', '检查内容', '判定标准', '异常处理'],
        [('应用服务', '进程状态、接口健康检查、错误日志', '无持续异常', '重启/回滚并排查'),
         ('数据库', '连接数、慢查询、锁等待、磁盘空间', '在阈值内', '优化/扩容/清理'),
         ('中间件', '缓存、消息队列、Web 服务器状态', '无堆积/无异常', '按组件手册处理'),
         ('资源', 'CPU、内存、磁盘、网络', '在阈值内', '扩容或优化'),
         ('证书与域名', '有效期、解析、链路', '未临近过期', '提前续期')]))

    lines.extend(['', '## 5. 服务级别（SLA）', '', '### 5.1 服务级别定义', ''])
    lines.extend(render_table(
        ['级别', '定义', '适用对象', '考核方式'],
        [('核心服务', '直接影响核心业务运行', '业务用户/管理员', '按月统计'),
         ('一般服务', '影响部分功能或效率', '业务用户', '按月统计'),
         ('支持服务', '咨询、培训、配置协助', '全员', '按季度统计')]))
    lines.extend(['', '### 5.2 响应与恢复指标', ''])
    lines.extend(render_table(
        ['指标', '目标值', '统计口径', '备注'],
        [('响应及时率', '待确认', '按时响应工单/工单总数', '按级别分别统计'),
         ('故障恢复及时率', '待确认', '按时恢复工单/工单总数', 'P0/P1 单独统计'),
         ('系统可用性', '待确认（建议 99.9%）', '可用时长/统计时长', '扣除约定维护窗口'),
         ('一次解决率', '待确认', '首次处理即关闭工单/工单总数', '按问题类型统计'),
         ('变更成功率', '待确认', '无回滚变更/变更总数', '按变更等级统计')]))
    lines.extend(['', '### 5.3 服务计量与报告', ''])
    lines.extend(render_table(
        ['报告项', '周期', '内容', '提交对象'],
        [('服务周报', '每周', '工单量、未结事项、风险提示', '项目组/业务方'),
         ('服务月报', '每月', 'SLA 达成、故障统计、变更统计、改进建议', '服务经理/业务方'),
         ('重大事件报告', '事件关闭后', '经过、影响、根因、整改与责任', '项目负责人/业务方'),
         ('季度复盘', '每季度', '服务趋势、容量与优化建议', '管理层')]))

    lines.extend(['', '## 6. 服务流程', '', '### 6.1 服务受理', ''])
    lines.extend(render_table(
        ['步骤', '输入', '处理动作', '输出', '责任方'],
        [('受理', '电话/工单/群消息', '记录问题、环境、影响与联系方式', '服务工单', '一线支持'),
         ('分类分级', '服务工单', '判断问题类型与故障级别', '分级结果', '一线支持'),
         ('分派', '分级结果', '按责任组分派并跟踪', '处理人', '服务经理'),
         ('处理', '工单与日志', '定位、修复或提供替代方案', '处理记录', '责任组'),
         ('验证', '处理结果', '与用户确认问题是否解决', '验证结论', '一线支持'),
         ('关闭', '验证结论', '填写根因、解决方案并关闭', '关闭工单', '一线支持')]))
    lines.extend(['', '### 6.2 事件分级与处理', ''])
    lines.append('- 事件分级依据业务影响、受影响用户范围、是否有替代方案综合判断')
    lines.append('- P0/P1 事件必须建立事件群、指定指挥人并按固定节奏同步进展')
    lines.append('- 处理过程记录时间点、操作人、关键结论与证据，禁止事后补记关键事实')
    lines.extend(['', '### 6.3 问题管理', ''])
    lines.append('- 重复出现或根因未明的事件转为问题单，指定责任人跟踪')
    lines.append('- 问题关闭需有根因分析、整改措施与验证记录')
    lines.extend(['', '### 6.4 变更管理', ''])
    lines.append('- 所有生产变更走变更单，禁止口头或私下变更')
    lines.append('- 高风险变更需准备回滚包、验证清单与值守安排')
    lines.extend(['', '### 6.5 服务关闭与回访', ''])
    lines.append('- 工单关闭前与用户确认结果，关闭后按需回访')
    lines.append('- 对 P0/P1 事件和不满意工单进行复盘与改进跟踪')

    lines.extend(['', '## 7. 服务资源与保障', '', '### 7.1 人员与工具', ''])
    lines.extend(render_table(
        ['资源类型', '内容', '状态'],
        [('服务台/工单系统', '受理、分派、跟踪与统计', '待确认'),
         ('监控平台', '可用性、接口、资源与日志监控', '待确认'),
         ('知识库', '常见问题、处理手册、变更记录', '待确认'),
         ('远程/现场支持', '按问题需要提供', '待确认'),
         ('备件/备用环境', '关键资源故障时启用', '待确认')]))
    lines.extend(['', '### 7.2 风险与应急预案', ''])
    lines.extend(render_table(
        ['风险项', '影响', '预防措施', '应急措施'],
        [('核心服务不可用', '业务中断', '高可用部署、监控告警、容量评估', '切换/回滚/启用备用环境'),
         ('数据损坏或误删', '数据不一致', '备份、权限控制、操作审计', '按备份恢复并核对数据'),
         ('安全事件', '数据泄露/非法访问', '最小权限、审计、漏洞修复', '止损、取证、上报与整改'),
         ('关键人员缺失', '处理延迟', 'AB 角、知识库、交接机制', '启用备份人员或供应商支持'),
         ('第三方依赖故障', '部分功能不可用', 'SLA 约束、降级方案', '切换备用通道/人工处理')]))
    lines.extend(['', '## 8. 服务持续改进', ''])
    lines.append('- 每月复盘工单量、SLA 达成率、重复问题与变更成功率')
    lines.append('- 将高频问题沉淀到知识库，更新操作手册与培训材料')
    lines.append('- 对未达标项制定改进计划、责任人与完成时间，并在下一周期验证')
    lines.append('')
    lines.extend(render_appendix('service-plan', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_test_report(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = doc_features(data, pages)
    modules = doc_modules(data, pages, features)
    priority_counts = Counter(feature['priority'] for feature in features)
    core_features = [feature for feature in features if feature['priority'] == 'P0']
    source = 'PRD' if data.get('prd_features') else '原型解析数据'
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['test-report'])]
    is_prd = bool(data.get('prd_features'))
    intro_pages = [{'pageName': module['name']} for module in modules] if is_prd else pages
    lines.extend(render_intro(project_name, DOC_TITLES['test-report'], intro_pages, data.get('tool'),
                              data.get('root_path'), 'PRD' if is_prd else '原型',
                              '模块' if is_prd else '页面'))
    lines.extend(['', '> 本文件同时包含**功能测试报告**与**性能测试报告**两部分，避免功能与性能结论分散。'
                       '所有执行结果、指标与结论必须来自真实测试记录；无记录时统一标注“待执行/待确认”。', ''])

    lines.extend(['## 2. 测试概述', '', '### 2.1 测试目的', '',
                  f'本报告基于{source}整理，覆盖 {len(modules)} 个模块、{len(features)} 个功能项，'
                  '用于验证功能实现与 PRD/原型的一致性，并评估系统在目标负载下的性能表现。', '',
                  '- 验证核心功能、业务流程、权限与异常处理是否符合 PRD 与验收标准',
                  '- 验证接口、数据与页面交互的完整性',
                  '- 评估系统在预期并发与数据量下的响应时间、吞吐量与稳定性',
                  '- 形成缺陷清单、性能瓶颈与上线建议', '',
                  '### 2.2 测试范围', ''])
    lines.extend(render_module_table(modules))
    lines.extend(['', '### 2.3 测试依据', ''])
    lines.append('- PRD / 原型页面与交互定义')
    lines.append('- 功能清单与测试用例')
    lines.append('- 接口定义、数据字典与非功能需求')
    lines.append('- 业务方确认的验收标准与上线要求')
    lines.extend(['', '### 2.4 测试环境', ''])
    lines.extend(render_table(
        ['环境项', '配置要求', '实际值', '确认状态'],
        [('应用环境', '测试/预生产环境，版本与待上线版本一致', '待确认', '待确认'),
         ('应用版本', '本次测试版本号与构建号', '待确认', '待确认'),
         ('数据库', '类型、版本、数据量与生产接近', '待确认', '待确认'),
         ('中间件', '缓存、消息队列、Web 服务器', '待确认', '待确认'),
         ('服务器', 'CPU/内存/磁盘/网络配置', '待确认', '待确认'),
         ('客户端', '浏览器/终端型号与版本', '待确认', '待确认'),
         ('监控工具', 'APM、日志、数据库监控', '待确认', '待确认')]))
    lines.extend(['', '### 2.5 测试组织与进度', ''])
    lines.extend(render_table(
        ['阶段', '计划时间', '参与角色', '主要工作'],
        [('测试准备', '待确认', '测试/开发', '环境、数据、用例与脚本准备'),
         ('功能测试', '待确认', '测试/业务', '执行用例、记录缺陷、回归验证'),
         ('性能测试', '待确认', '测试/运维/开发', '压测脚本、基线测试、加压与调优'),
         ('测试总结', '待确认', '项目组', '汇总结果、缺陷、风险与上线建议')]))

    lines.extend(['', '## 3. 测试对象与策略', '', '### 3.1 测试对象', ''])
    feature_rows = []
    for feature in features[:60]:
        feature_rows.append((feature['id'], feature['module'], feature['name'], feature['priority'],
                             len(feature.get('acceptance') or [])))
    lines.extend(render_table(['编号', '模块', '功能', '优先级', '验收标准数'], feature_rows,
                              empty_row=['待补充', '-', '-', '-', '0']))
    lines.extend(['', '### 3.2 测试类型与策略', ''])
    lines.extend(render_table(
        ['测试类型', '测试内容', '方法', '是否纳入'],
        [('功能测试', '页面、字段、按钮、流程、规则', '黑盒用例 + 业务场景', '是'),
         ('接口测试', '请求/响应、状态码、异常与幂等', '接口工具/自动化', '待确认'),
         ('权限测试', '角色、菜单、按钮与数据权限', '多角色交叉验证', '待确认'),
         ('兼容性测试', '浏览器/终端/分辨率', '目标矩阵抽样', '待确认'),
         ('异常测试', '空值、超长、非法格式、并发冲突', '边界值 + 故障注入', '待确认'),
         ('性能测试', '响应时间、吞吐量、并发、稳定性', '压测工具 + 监控', '是'),
         ('安全测试', '认证、越权、注入、敏感信息', '安全扫描 + 人工验证', '待确认')]))
    lines.extend(['', '### 3.3 测试准入与退出标准', ''])
    lines.extend(render_table(
        ['类型', '准入标准', '退出标准'],
        [('功能测试', '版本可部署、核心流程可走通、用例与数据就绪',
          'P0/P1 用例全部执行，阻塞缺陷清零，遗留缺陷有明确处理计划'),
         ('性能测试', '功能基线稳定、压测环境与数据就绪、监控可用',
          '目标场景完成，指标达到确认目标或形成明确优化结论')]))

    lines.extend(['', '## 4. 功能测试报告', '', '### 4.1 功能测试方法', ''])
    lines.append('- 以 PRD 功能项与验收标准为依据设计用例，覆盖正常、边界与异常场景')
    lines.append('- 按模块执行，记录实际结果、证据与缺陷编号')
    lines.append('- 缺陷修复后进行回归，回归通过后方可关闭')
    lines.append('- 业务关键流程由业务方参与验收确认')
    lines.extend(['', '### 4.2 用例执行汇总', ''])
    lines.extend(render_table(
        ['统计项', '数量', '说明'],
        [('功能项总数', len(features), '来自 PRD/原型功能项'),
         ('P0 功能', priority_counts.get('P0', 0), '核心功能'),
         ('P1 功能', priority_counts.get('P1', 0), '重要功能'),
         ('P2 功能', priority_counts.get('P2', 0), '一般功能'),
         ('计划用例数', '待确认', '以测试用例文档为准'),
         ('已执行用例数', '待执行', '测试完成后填写'),
         ('通过用例数', '待执行', '测试完成后填写'),
         ('失败用例数', '待执行', '测试完成后填写'),
         ('阻塞用例数', '待执行', '测试完成后填写'),
         ('用例通过率', '待确认', '通过数/已执行数')]))
    lines.extend(['', '### 4.3 功能测试结果明细', ''])
    result_rows = []
    for feature in features[:60]:
        result_rows.append((feature['id'], feature['module'], feature['name'], feature['priority'],
                            '待执行', '-', '待确认'))
    lines.extend(render_table(['编号', '模块', '功能', '优先级', '执行结果', '缺陷编号', '备注'],
                              result_rows, empty_row=['待补充', '-', '-', '-', '待执行', '-', '待确认']))
    lines.extend(['', '### 4.4 缺陷统计与分析', ''])
    lines.extend(render_table(
        ['统计项', '数量', '说明'],
        [('缺陷总数', '待记录', '测试完成后填写'),
         ('阻塞级', '待记录', '导致核心流程无法继续'),
         ('严重级', '待记录', '核心功能异常或数据错误'),
         ('一般级', '待记录', '非核心功能异常'),
         ('建议级', '待记录', '体验与优化建议'),
         ('已关闭', '待记录', '回归通过并关闭'),
         ('遗留缺陷', '待记录', '需明确规避方案与修复计划')]))
    lines.extend(['', '### 4.5 功能缺陷清单', ''])
    lines.extend(render_table(
        ['编号', '模块', '问题描述', '严重级别', '状态', '责任人', '计划修复时间'],
        [('BUG-001', '待确认', '测试完成后补充现象、复现步骤、预期与实际', '待确认',
          '待处理', '待确认', '待确认')]))
    lines.extend(['', '### 4.6 功能测试结论', '',
                  '待功能测试完成后填写：核心功能是否全部通过、遗留缺陷是否影响上线、'
                  '是否需要回归或扩大测试范围。原型/PRD 只能说明“应测试什么”，不能替代真实执行记录。', ''])

    lines.extend(['## 5. 性能测试报告', '', '### 5.1 性能测试目标', ''])
    lines.extend(render_table(
        ['指标', '目标值', '说明'],
        [('页面平均响应时间', '待确认（建议 ≤ 2 秒）', '核心页面在正常负载下的平均响应'),
         ('核心接口响应时间', '待确认（建议 P95 ≤ 500 毫秒）', '按接口分别设定'),
         ('系统吞吐量', '待确认', '每秒/每分钟成功请求数'),
         ('并发用户数', '待确认', '按业务峰值估算'),
         ('错误率', '待确认（建议 < 1%）', '压测期间失败请求占比'),
         ('CPU/内存使用率', '待确认（建议 < 80%）', '稳定压测期间的资源水位'),
         ('稳定性运行时长', '待确认（建议 ≥ 2 小时）', '持续负载下无内存泄漏/连接耗尽')]))
    lines.extend(['', '### 5.2 性能测试场景设计', ''])
    scenario_source = core_features or features
    scenario_rows = []
    scenario_names = [
        ('查询类场景', '列表查询、筛选、分页'),
        ('提交类场景', '表单填写与提交'),
        ('详情类场景', '详情查看与关联数据加载'),
        ('混合业务场景', '按真实业务比例混合操作'),
        ('稳定性场景', '持续负载下长时间运行'),
    ]
    for index, (name, description) in enumerate(scenario_names, 1):
        related = '、'.join(feature['name'] for feature in scenario_source[:4]) or '待确认'
        scenario_rows.append((f'PT-{index:02d}', name, description, related,
                              '待确认', '待确认', '待确认'))
    lines.extend(render_table(['编号', '场景', '业务描述', '关联功能', '并发数', '持续时间', '通过标准'],
                              scenario_rows))
    lines.extend(['', '### 5.3 测试数据与模型', ''])
    lines.extend(render_table(
        ['项目', '要求', '实际值', '确认状态'],
        [('数据量', '与生产同量级或按比例缩放并说明', '待确认', '待确认'),
         ('数据分布', '覆盖正常、边界与热点数据', '待确认', '待确认'),
         ('压测模型', '并发用户、思考时间、操作比例', '待确认', '待确认'),
         ('压测工具', 'JMeter/Locust/k6 等', '待确认', '待确认'),
         ('监控采样', '应用、数据库、系统资源指标', '待确认', '待确认')]))
    lines.extend(['', '### 5.4 性能指标汇总', ''])
    lines.extend(render_table(
        ['场景', '并发数', '平均响应时间', 'P95 响应时间', 'TPS/QPS', '错误率', '结论'],
        [(row[0], row[4], '待执行', '待执行', '待执行', '待执行', '待确认')
         for row in scenario_rows]))
    lines.extend(['', '### 5.5 压测结果与趋势', '',
                  '待压测完成后补充：各场景的响应时间曲线、TPS/QPS 趋势、资源使用曲线、'
                  '错误分布与拐点分析。不得在无压测数据时填写“通过”。', ''])
    lines.extend(['', '### 5.6 瓶颈分析与调优建议', ''])
    lines.extend(render_table(
        ['可能瓶颈', '判断依据', '调优方向', '验证方式'],
        [('数据库慢查询', '慢查询日志、锁等待、CPU 高', '索引优化、SQL 改写、分页与缓存', '优化后重跑同场景'),
         ('接口耗时', 'APM 调用链、单接口 P95 高', '减少串行调用、异步化、批量接口', '对比优化前后指标'),
         ('缓存命中率低', '缓存命中率、回源请求量', '调整缓存键/过期策略、预热', '观察命中率与响应时间'),
         ('连接池不足', '连接等待、超时错误', '调整连接池大小与超时', '压测验证错误率'),
         ('资源不足', 'CPU/内存/磁盘/网络达到阈值', '扩容、限流、降级', '容量测试验证'),
         ('前端资源过大', '页面加载瀑布图', '压缩、懒加载、CDN', '前端性能测试')]))
    lines.append('')
    lines.append('- 调优必须基于压测数据，禁止凭经验直接下结论')
    lines.append('- 每次调优记录变更内容、前后指标与验证结论')
    lines.append('- 未达标的场景明确是否阻塞上线、规避方案与后续优化计划')
    lines.extend(['', '### 5.7 性能测试结论', '',
                  '待性能测试完成后填写：目标场景是否达标、是否存在阻塞上线的性能风险、'
                  '需要扩容或优化的项及验证结果。', ''])

    lines.extend(['## 6. 测试结论与上线建议', '', '### 6.1 综合结论', ''])
    lines.extend(render_table(
        ['测试类型', '执行情况', '结论', '阻塞上线'],
        [('功能测试', '待执行', '待确认', '待确认'),
         ('性能测试', '待执行', '待确认', '待确认'),
         ('接口/权限/兼容性', '待确认', '待确认', '待确认')]))
    lines.extend(['', '### 6.2 遗留问题与风险', ''])
    lines.extend(render_table(
        ['问题/风险', '影响', '应对措施', '责任人', '计划完成时间'],
        [('核心功能缺陷未关闭', '影响业务使用', '修复后回归，必要时缩小上线范围', '待确认', '待确认'),
         ('性能指标未达标', '影响用户体验/稳定性', '扩容、优化或限流降级', '待确认', '待确认'),
         ('测试覆盖不足', '存在未知缺陷', '补充用例与回归范围', '待确认', '待确认'),
         ('环境与生产差异', '测试结论代表性不足', '补充预生产验证', '待确认', '待确认')]))
    lines.extend(['', '### 6.3 上线建议', '',
                  '待测试完成后填写“建议上线 / 有条件上线 / 不建议上线”，并列出限制条件、'
                  '必须关闭的缺陷与上线后观察指标。', ''])
    lines.extend(render_appendix('test-report', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_doc_frontmatter(project_name, version, doc_title):
    today = datetime.date.today().isoformat()
    return '\n'.join([
        f'# {project_name} {doc_title}',
        '',
        f'> 版本: v{version} | 更新日期: {today} | 文档类型: {doc_title}',
        '',
    ])


def render_intro(project_name, doc_title, pages, tool, root_path, source_label='原型', unit='页面'):
    page_names = [page.get('pageName') or '未命名页面' for page in pages]
    if not page_names:
        scope = f'{source_label}中未识别到可访问{unit}，适用范围待补充。'
    elif len(page_names) <= 12:
        scope = f'覆盖{source_label}中的 {len(pages)} 个{unit}：{as_text(page_names)}。'
    else:
        scope = f'覆盖{source_label}中的 {len(pages)} 个{unit}，包括 {as_text(page_names[:12])} 等{unit}。'
    if source_label == 'PRD':
        first_term = ('PRD', '产品需求文档，包含功能项、角色、字段、验收标准与业务规则')
        first_count = ('模块', 'PRD 功能清单中的一个业务模块')
        reference_terms = [('输入来源', 'PRD 文档路径'), ('模块数量', str(len(pages)))]
    else:
        first_term = ('原型', '原型工具导出的 HTML/Schema 页面集合')
        first_count = ('页面', '原型中的一个可访问页面或画板')
        reference_terms = [('原型解析工具', as_text(tool, '未知')),
                           ('原型根目录', as_text(root_path, '未提供')),
                           ('页面数量', str(len(pages)))]
    glossary = [
        first_term,
        first_count,
        ('字段', '页面中出现的标签、控件或表格列推断出的数据项'),
        ('P0/P1/P2', '功能优先级：P0 核心、P1 重要、P2 一般'),
        ('待确认', '输入材料未体现、需业务方/开发/DBA 确认的内容'),
    ]
    purposes = {
        '系统概要说明书': f'本文档用于说明 {project_name} 的建设目标、总体架构、功能范围与非功能要求，作为设计评审、开发实现、测试验收与上线运维的依据。',
        '详细说明书': f'本文档用于说明 {project_name} 各模块的功能构成、处理流程、交互规则与异常处理，作为开发实现、联调与测试验收的依据。',
        '数据库设计说明书': f'本文档用于说明 {project_name} 的数据库选型、逻辑模型、物理表结构与索引设计，作为开发与 DBA 建库建表的依据。',
        '试运行报告': f'本文档用于记录 {project_name} 试运行的环境、范围、执行过程、问题与结论，作为上线决策与整改验收的依据。',
        '维护手册': f'本文档用于说明 {project_name} 的日常巡检、故障处理、变更发布与应急恢复要求，作为运维团队接手系统的操作依据。',
        '操作手册': f'本文档用于说明 {project_name} 的访问方式、角色权限与各功能操作步骤，作为最终用户培训与日常使用的依据。',
        '应用软件清单': f'本文档用于盘点 {project_name} 涉及的应用软件、基础组件、版本与许可信息，作为部署、采购与资产管理的依据。',
        '系统参数配置说明': f'本文档用于说明 {project_name} 的系统参数、业务参数、默认值与配置变更流程，作为部署实施与运维配置的依据。',
        '培训计划': f'本文档用于规划 {project_name} 的培训目标、对象、课程、组织与考核安排，作为上线前用户培训与效果评估的依据。',
        '服务计划': f'本文档用于明确 {project_name} 的服务范围、组织职责、服务级别与工作流程，作为上线后运维支持与服务考核的依据。',
        '功能与性能测试报告': f'本文档用于记录 {project_name} 的功能测试与性能测试范围、执行结果、缺陷、指标与结论，作为上线决策的依据。',
    }
    purpose = purposes.get(doc_title, f'本文档用于说明 {project_name} 的{doc_title}相关内容。')
    lines = ['## 1. 引言', '', '### 1.1 编写目的', '', purpose, '',
             '### 1.2 适用范围', '', scope, '']
    lines.extend(['### 1.3 术语与缩略语', '', '| 术语 | 说明 |', '|------|------|'])
    for term, definition in glossary:
        lines.append(f'| {cell(term)} | {cell(definition)} |')
    lines.extend(['', '### 1.4 参考资料', ''])
    for label, value in reference_terms:
        if label == '输入来源':
            lines.append(f'- {label}：{as_text(root_path, value)}')
        else:
            lines.append(f'- {label}：{value}')
    lines.append('')
    return lines


def render_module_table(modules):
    lines = ['| 序号 | 模块 | 功能项数 | 主要功能 |', '|------|------|----------|----------|']
    if modules:
        for index, module in enumerate(modules, 1):
            names = '、'.join(feature['name'] for feature in module['features'][:4])
            if len(module['features']) > 4:
                names += ' 等'
            lines.append(f'| {index} | {cell(module["name"])} | {len(module["features"])} | {cell(names)} |')
    else:
        lines.append('| - | 待补充 | 0 | - |')
    return lines


def render_roles_table(roles):
    lines = ['| 角色 | 职责说明 |', '|------|----------|']
    for role in roles:
        lines.append(f'| {cell(role["name"])} | {cell(role["description"])} |')
    if not roles:
        lines.append('| 待补充 | - |')
    return lines


def render_interfaces_table(interfaces):
    lines = ['| 接口名称 | 类型 | 提供方 | 调用方 | 说明 |', '|----------|------|--------|--------|------|']
    for item in interfaces:
        lines.append(
            f'| {cell(item["name"])} | {cell(item["type"])} | {cell(item["provider"])} '
            f'| {cell(item["caller"])} | {cell(item["description"])} |'
        )
    if not interfaces:
        lines.append('| 待补充 | - | - | - | 原型未提供接口定义 |')
    return lines


def render_entity_summary(entities):
    lines = ['| 实体 | 表名 | 说明 | 字段数 |', '|------|------|------|--------|']
    for entity in entities:
        lines.append(
            f'| {cell(entity["name"])} | {cell(entity["table_name"])} '
            f'| {cell(entity["description"])} | {len(entity["fields"])} |'
        )
    if not entities:
        lines.append('| 待补充 | - | - | 0 |')
    return lines


def render_nfr_table():
    lines = ['| NFR 项 | 默认基线 | 触发特殊提问的条件 |', '|--------|----------|--------------------|']
    for item in DEFAULT_NFR:
        lines.append(f'| {cell(item["item"])} | {cell(item["baseline"])} | {cell(item["condition"])} |')
    return lines


def render_relations(relations):
    lines = []
    for relation in relations:
        lines.append(
            f'- **{cell(relation["from"])} → {cell(relation["to"])}**'
            f'（{cell(relation["type"])}）: {cell(relation["description"])}'
        )
    return lines or ['- 待补充（原型未提供实体关系，以上为页面命名推断）']


def render_source_note(doc_type, data, pages, entities, skipped):
    is_prd = bool(data.get('prd_features'))
    notes_included = any(page.get('notes') for page in pages)
    ambiguous = []
    for page in pages:
        for field in page.get('ambiguous_fields') or []:
            label = clean_label(field.get('label'))
            if label and not is_noise_label(label):
                ambiguous.append(f'{page.get("pageName")}「{label}」')
    lines = ['### 数据来源说明', '']
    lines.append(f'- 解析工具：{as_text(data.get("tool"), "未知")}')
    lines.append(f'- {"PRD 路径" if is_prd else "原型目录"}：{as_text(data.get("root_path"), "未提供")}')
    lines.append(f'- 覆盖{"模块" if is_prd else "页面"}：{len(pages)} 个')
    if entities:
        lines.append(f'- 推断实体：{len(entities)} 个（表名、字段名、类型、索引均为建议，需后端/DBA 确认）')
    if skipped and not is_prd:
        lines.append(f'- 未纳入表设计的页面：{as_text(skipped)}')
    note_targets = {
        'system-overview': '功能描述、功能边界或待确认项',
        'detailed-design': '业务规则、交互步骤或待确认项',
        'database-design': '字段说明、索引建议或待确认项',
        'trial-run-report': '验证记录、问题清单或待确认项',
        'maintenance-manual': '巡检项、故障处理或待确认项',
        'operation-manual': '操作步骤、字段说明或待确认项',
        'application-inventory': '软件条目、版本信息或待确认项',
        'system-parameters': '参数说明、默认值或待确认项',
        'training-plan': '培训内容、课程安排或待确认项',
        'service-plan': '服务内容、SLA 或待确认项',
        'test-report': '测试范围、场景、缺陷或待确认项',
    }
    if notes_included:
        lines.append(f'- 便签/矩形内备注说明已纳入{note_targets.get(doc_type, "功能描述或待确认项")}')
    else:
        lines.append('- PRD 未包含便签/备注说明' if is_prd else '- 未发现便签/矩形内备注说明')
    if ambiguous:
        lines.append(f'- 模糊字段 {len(ambiguous)} 个，需先确认：{as_text(ambiguous[:10])}')
    if is_prd:
        lines.append('- 字段类型与验收标准取自 PRD；PRD 未明确的必填、默认值、校验规则标“待确认”')
    else:
        lines.append('- 字段类型优先取控件类型，缺失时按标签推断；必填、默认值、校验规则原型未体现时标“待确认”')
    lines.append('')
    return lines


def render_appendix(doc_type, data, pages, entities, skipped, version):
    pending = []
    for page in pages:
        page_name = page.get('pageName') or '未命名页面'
        for field in page.get('ambiguous_fields') or []:
            label = clean_label(field.get('label'))
            reason = as_text(field.get('reason'), '控件类型无法确定')
            if label and not is_noise_label(label):
                pending.append(f'`{page_name}` 字段「{label}」：{reason}')
        if page.get('is_screenshot_composite'):
            pending.append(f'`{page_name}`：检测到截图拼接（{as_text(page.get("screenshot_evidence"), "无证据")}），字段与控件可能提取不全')
    if not entities and doc_type in ('database-design', 'system-overview', 'detailed-design'):
        pending.append('原型未识别到可用字段，实体与表设计待补充')
    if doc_type == 'database-design':
        pending.append('表名、字段名、字段类型、长度、索引均为原型推断建议，需后端与 DBA 最终确认')
        pending.append('原型未提供分库分表、数据量、备份与合规要求，需补充后再定稿')
    elif doc_type == 'detailed-design':
        pending.append('接口请求/响应结构、错误码、权限矩阵需后端与前端补充')
    elif doc_type == 'trial-run-report':
        pending.append('试运行时间、环境地址、参与人员、实测指标与缺陷记录原型未体现，需试运行组织方补充')
        pending.append('试运行结论必须基于真实执行记录，不得仅凭原型直接判定通过')
    elif doc_type == 'maintenance-manual':
        pending.append('部署拓扑、监控阈值、备份策略、值班联系人与升级路径需运维团队补充')
        pending.append('故障处理命令、日志路径与恢复步骤需按实际部署环境核实')
    elif doc_type == 'operation-manual':
        pending.append('访问地址、账号开通方式、按钮级权限与业务校验规则原型未体现，需业务方与实施团队补充')
        pending.append('操作步骤中的“待确认”项需在 UAT 环境实测后修订')
    elif doc_type == 'application-inventory':
        pending.append('软件名称、版本、许可类型、部署位置与责任人原型未体现，需运维/采购/资产管理方补充')
        pending.append('基础软件条目为通用基线建议，不代表已采购或已部署')
    elif doc_type == 'system-parameters':
        pending.append('参数默认值、取值范围、生效方式与敏感级别原型未体现，需开发与运维补充')
        pending.append('业务参数由配置页面字段推断，是否作为系统参数需业务方确认')
    elif doc_type == 'training-plan':
        pending.append('培训时间、地点、人数、讲师与考核标准需培训组织方补充')
        pending.append('课程课时为按功能项数量给出的建议值，需结合受众基础与培训时长确认')
        pending.append('培训环境、账号与演示数据需在培训前准备并验证')
    elif doc_type == 'service-plan':
        pending.append('服务组织、人员姓名、联系方式、服务窗口与合同约定需服务提供方补充')
        pending.append('SLA 目标值、响应/恢复时限与考核口径需双方确认后生效')
        pending.append('监控工具、工单系统、知识库与备份策略需结合实际运维环境核实')
    elif doc_type == 'test-report':
        pending.append('测试环境、执行时间、测试人员、用例执行记录与缺陷编号需测试团队补充')
        pending.append('性能目标值、并发模型、数据量与压测结果原型/PRD 未体现，需在性能测试后填写')
        pending.append('功能与性能结论必须基于真实测试记录，不得仅凭 PRD 直接判定通过')
    else:
        pending.append('业务背景、建设目标、技术栈、部署方式原型未体现，需业务方补充')
    if skipped and not data.get('prd_features'):
        pending.append(f'以下页面未纳入表设计：{as_text(skipped)}')

    lines = ['## 附录', '', '### 待确认事项', '']
    for item in unique(pending)[:30]:
        lines.append(f'- {item}')
    if not pending:
        lines.append('- 暂无')
    lines.extend(['', '### 变更历史', '', '| 版本 | 日期 | 变更内容 | 变更人 |',
                  '|------|------|----------|--------|',
                  f'| v{version} | {datetime.date.today().isoformat()} | 初始版本 | - |', ''])
    lines.extend(render_source_note(doc_type, data, pages, entities, skipped))
    return lines


def render_system_overview(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = build_features(pages)
    modules = build_modules(pages, features)
    roles = infer_roles(pages)
    interfaces = infer_interfaces(entities, pages)
    relations = infer_relations(entities)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['system-overview'])]
    lines.extend(render_intro(project_name, DOC_TITLES['system-overview'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 系统概述', '', '### 2.1 项目背景', '',
                  f'本系统由原型导出内容推断，覆盖 {len(pages)} 个页面。'
                  '原型未提供业务背景、现状问题与建设动因，需业务方补充。', '',
                  '### 2.2 建设目标', ''])
    if modules:
        top_modules = sorted(modules, key=lambda item: (-len(item['features']), item['name']))[:6]
        category_labels = {
            'admin_console': '管理后台', 'config_page': '配置页面',
            'form_page': '表单页面', 'list_page': '列表页面',
            'detail_page': '详情页面', 'flow_diagram': '流程页面',
            'image_composite': '图文页面', 'dashboard': '数据看板',
            'login_page': '登录页面', 'mobile_page': '移动页面',
            'unknown': '其他页面',
        }
        category_counts = Counter(page.get('page_category') or 'unknown' for page in pages)
        distribution = [f'{category_labels.get(key, key)} {count} 个'
                        for key, count in category_counts.most_common()]
        lines.append(f'- 覆盖 {len(modules)} 个模块、{len(features)} 个功能项')
        lines.append('- 重点模块：' + as_text([f'{item["name"]}（{len(item["features"])} 项）'
                                          for item in top_modules]))
        lines.append('- 页面类型分布：' + as_text(distribution))
    else:
        lines.append('- 待补充')
    lines.extend(['', '### 2.3 用户角色', ''])
    lines.extend(render_roles_table(roles))
    lines.extend(['', '### 2.4 运行环境', '', '- **技术栈**: 待确认（原型未声明）',
                  '- **部署方式**: 待确认（原型未声明）',
                  '- **运行环境**: 待确认（服务器、操作系统、中间件、网络要求）', ''])

    lines.extend(['## 3. 总体设计', '', '### 3.1 设计原则', '',
                  '- 职责单一：模块边界清晰，避免跨模块耦合',
                  '- 可扩展：预留功能扩展与容量扩展能力',
                  '- 安全合规：敏感数据加密传输与最小权限访问',
                  '- 可运维：统一日志、监控与告警', '',
                  '### 3.2 系统架构', '',
                  '- **架构风格**: 待确认（原型仅体现前端页面与交互）',
                  '- **技术栈**: 待确认',
                  '- **部署方式**: 待确认', '',
                  '**建议分层（待确认）**', '',
                  '| 层次 | 职责 |', '|------|------|',
                  '| 接入层 | 网关、鉴权、限流 |',
                  '| 页面层 | 原型页面的展示与交互 |',
                  '| 应用层 | 业务编排与事务控制 |',
                  '| 数据层 | 数据持久化、缓存与检索 |', '',
                  '**核心组件（按页面模块推断）**', '',
                  '| 组件 | 说明 |', '|------|------|'])
    for module in modules[:12]:
        lines.append(f'| {cell(module["name"])} | {cell(category_label(module["category"]))}，{len(module["features"])} 项功能 |')
    if not modules:
        lines.append('| 待补充 | - |')
    lines.extend(['', '### 3.3 模块划分', ''])
    lines.extend(render_module_table(modules))

    lines.extend(['', '### 3.4 核心业务流程', ''])
    flow_lines = []
    for page in pages:
        steps = interaction_steps(page, limit=3, business_only=True)
        if steps:
            flow_lines.append(f'- **{page.get("pageName")}**: {as_text(steps)}')
    lines.extend(flow_lines or ['- 原型未提取到交互事件，核心业务流程待补充'])

    lines.extend(['', '### 3.5 部署与集成', '',
                  '- **部署拓扑**: 待确认（原型未体现）',
                  '- **第三方系统**: 待确认（原型未体现）',
                  '- **消息/定时任务**: 待确认（原型未体现）', ''])

    lines.extend(['', '## 4. 功能概要', '', '### 4.1 功能清单', '',
                  '| 编号 | 功能 | 所属模块 | 优先级 | 功能描述 |',
                  '|------|------|----------|--------|----------|'])
    for feature in features:
        lines.append(
            f'| {cell(feature["id"])} | {cell(feature["name"])} | {cell(feature["module"])} '
            f'| {cell(feature["priority"])} | {cell(feature["description"])} |'
        )
    if not features:
        lines.append('| - | 待补充 | - | - | - |')
    lines.extend(['', '### 4.2 功能边界', '',
                  '- **包含**：原型中可识别的页面主功能、筛选查询、表单填写与提交',
                  '- **不包含**：原型未体现的后端实现、权限模型、定时任务、第三方集成',
                  '- 具体功能描述见 4.1；详细交互与异常规则见《详细说明书》', ''])

    lines.extend(['## 5. 接口概要', '',
                  '> 原型未提供接口定义，以下为按页面操作推断的建议接口，需后端确认。', ''])
    lines.extend(render_interfaces_table(interfaces))

    lines.extend(['', '## 6. 数据与实体概要', '', '### 6.1 主要实体', ''])
    lines.extend(render_entity_summary(entities))
    lines.extend(['', '### 6.2 实体关系', ''])
    lines.extend(render_relations(relations))

    lines.extend(['', '## 7. 非功能需求', '',
                  '> 以下为默认基线（待确认），如无特殊场景可直接沿用。', ''])
    lines.extend(render_nfr_table())

    lines.extend(['', '## 8. 约束与假设', '', '### 8.1 约束条件', '',
                  '- 原型仅提供页面、控件与交互，不含后端、数据库、部署信息',
                  '- 字段、接口、表结构需在详细设计与数据库设计阶段确认', '',
                  '### 8.2 前提假设', '',
                  '- 页面名称近似代表业务模块',
                  '- 原型文本与控件即当前需求来源',
                  '- 原型未展示的规则不视为已确认需求', ''])
    lines.extend(render_appendix('system-overview', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_feature_fields(feature):
    fields = feature.get('fields') or []
    if not fields:
        return []
    lines = ['**字段说明**', '', '| 字段名 | 类型 | 必填 | 校验规则 | 默认值 | 说明 |',
             '|--------|------|------|----------|--------|------|']
    for field in fields:
        lines.append(
            f'| {cell(field["name"])} | {cell(field["type"])} | {cell(field["required"])} '
            f'| 待确认 | {cell(field["default"])} | {cell(field["description"])} |'
        )
    lines.append('')
    return lines


def render_feature_actions(feature):
    actions = feature.get('actions') or []
    if not actions:
        return []
    lines = ['**按钮/操作逻辑**', '', '| 按钮/操作 | 触发条件 | 操作行为 | 异常处理 |',
             '|-----------|----------|----------|----------|']
    for action in actions:
        lines.append(f'| {cell(action)} | 待确认 | 触发「{cell(action)}」操作 | 待确认 |')
    lines.append('')
    return lines


def render_feature_acceptance(feature):
    lines = ['**验收标准**', '']
    for item in feature.get('acceptance') or ['待补充']:
        lines.append(f'- [ ] {item}')
    lines.append('')
    return lines


def render_detailed_design(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    features = build_features(pages)
    modules = build_modules(pages, features)
    interfaces = infer_interfaces(entities, pages)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['detailed-design'])]
    lines.extend(render_intro(project_name, DOC_TITLES['detailed-design'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 总体说明', '', '### 2.1 设计范围', ''])
    lines.append(f'本期覆盖 {len(pages)} 个页面、{len(modules)} 个模块、{len(features)} 个功能项。')
    lines.extend(['', '### 2.2 模块划分', ''])
    lines.extend(render_module_table(modules))
    lines.extend(['', '### 2.3 设计约定', '',
                  '- 接口统一采用 RESTful 风格，返回结构统一为 {code, message, data}',
                  '- 错误码按模块分段管理，异常信息不得向前端暴露堆栈细节',
                  '- 关键操作记录操作日志，敏感字段脱敏后输出',
                  '- 统一使用 UTC+8 时区，时间字段精确到秒',
                  '- 原型未体现的规则、字段与接口一律标“待确认”，不得臆造', ''])

    lines.extend(['## 3. 模块详细设计', ''])
    for module_index, module in enumerate(modules, 1):
        lines.append(f'### 3.{module_index} {module["name"]}')
        lines.append('')
        lines.append(f'#### 3.{module_index}.1 模块职责')
        lines.append('')
        lines.append(f'负责「{module["name"]}」页面的业务处理与数据维护（页面类型：{category_label(module["category"])}）。')
        lines.append('')
        lines.append(f'#### 3.{module_index}.2 功能构成')
        lines.append('')
        lines.append('| 编号 | 功能 | 优先级 | 功能描述 |')
        lines.append('|------|------|--------|----------|')
        for feature in module['features']:
            lines.append(f'| {cell(feature["id"])} | {cell(feature["name"])} | {cell(feature["priority"])} | {cell(feature["description"])} |')
        if not module['features']:
            lines.append('| - | 待补充 | - | - |')
        lines.append('')
        lines.append(f'#### 3.{module_index}.3 处理流程与交互')
        lines.append('')
        for feature in module['features']:
            lines.append(f'**{feature["id"]} {feature["name"]}**')
            lines.append('')
            if feature.get('flow'):
                for step in feature['flow']:
                    lines.append(f'- {step}')
            else:
                lines.append('- 原型未提取到交互事件，处理流程待补充')
            lines.append('')
        lines.append(f'#### 3.{module_index}.4 业务规则与异常处理')
        lines.append('')
        rules = []
        for feature in module['features']:
            for rule in feature.get('business_rules') or []:
                rules.append(f'- **{feature["name"]}**: {rule}')
            if not feature.get('business_rules'):
                rules.append(f'- **{feature["name"]}**：原型未提供明确业务规则，校验与异常策略待确认')
        lines.extend(unique(rules) or ['- 待补充'])
        lines.append('')

    lines.extend(['## 4. 功能明细', ''])
    for index, feature in enumerate(features, 1):
        lines.append(f'### 4.{index} {feature["id"]} {feature["name"]}')
        lines.append('')
        lines.append('| 属性 | 值 |')
        lines.append('|------|-----|')
        lines.append(f'| 所属模块 | {cell(feature["module"])} |')
        lines.append(f'| 优先级 | {cell(feature["priority"])} |')
        lines.append(f'| 所属页面 | {cell(feature["page"])} |')
        lines.append('')
        lines.append('**功能描述**')
        lines.append('')
        lines.append(feature['description'])
        lines.append('')
        lines.extend(render_feature_fields(feature))
        lines.extend(render_feature_actions(feature))
        lines.extend(render_feature_acceptance(feature))

    lines.extend(['## 5. 接口详细设计', '',
                  '> 原型未提供接口定义，以下为建议接口，请求/响应结构与错误码需后端补充。', ''])
    lines.extend(render_interfaces_table(interfaces))
    lines.extend(['', '## 6. 数据设计', ''])
    lines.extend(render_entity_summary(entities))
    lines.extend(['', '> 完整字段、索引与约束详见《数据库设计说明书》。', ''])
    lines.extend(['## 7. 日志、异常与安全', '', '### 7.1 日志设计', '',
                  '关键业务操作、登录行为与异常错误均需记录日志，日志保留不少于 180 天（默认基线，待确认）。',
                  '', '### 7.2 异常处理', '',
                  '统一异常拦截，按错误码返回友好提示；不可恢复异常记录上下文并告警（默认基线，待确认）。',
                  '', '### 7.3 安全设计', '',
                  '传输层加密、登录态校验、接口鉴权、敏感数据脱敏与最小权限控制（默认基线，待确认）。', ''])
    lines.extend(render_appendix('detailed-design', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def render_database_design(data, pages, entities, skipped, version):
    project_name = data.get('project_name') or '未命名项目'
    relations = infer_relations(entities)
    lines = [render_doc_frontmatter(project_name, version, DOC_TITLES['database-design'])]
    lines.extend(render_intro(project_name, DOC_TITLES['database-design'], pages, data.get('tool'), data.get('root_path')))

    lines.extend(['## 2. 设计概述', '', '### 2.1 设计原则', '',
                  '- 满足第三范式，必要时为查询性能做冗余',
                  '- 所有表统一主键、创建时间与更新时间字段',
                  '- 不使用物理外键，关联关系由应用层保证',
                  '- 敏感字段加密存储，禁止明文落库',
                  '- 表名、字段名与索引均需后端/DBA 复核', ''])
    lines.extend(['### 2.2 数据库选型与环境', '',
                  '- **数据库**: MySQL 8.0（默认，待确认）',
                  '- **字符集**: utf8mb4',
                  '- **排序规则**: utf8mb4_general_ci',
                  '- **时区**: UTC+8', ''])
    lines.extend(['### 2.3 命名规范', '',
                  '| 对象 | 规范 | 示例 |', '|------|------|------|',
                  '| 表名 | `t_` 前缀 + 小写下划线 | `t_instance` |',
                  '| 字段名 | 小写下划线 | `created_at` |',
                  '| 主键 | 统一 `id` | `id` |',
                  '| 外键 | `<实体>_id` | `instance_id` |',
                  '| 索引 | `idx_表名_字段` / `uk_表名_字段` | `idx_instance_status` |', ''])
    lines.extend(['### 2.4 数据类型规范', '',
                  '| 场景 | 类型 | 说明 |', '|------|------|------|',
                  '| 主键 | `bigint` | 自增或雪花 ID |',
                  '| 短文本 | `varchar(n)` | 按实际长度设置，避免滥用 text |',
                  '| 长文本 | `text` / `longtext` | 富文本、日志等 |',
                  '| 金额 | `decimal(18,2)` | 禁止使用浮点类型 |',
                  '| 时间 | `datetime` | 精确到秒 |',
                  '| 布尔 | `tinyint(1)` | 0/1 |',
                  '| 枚举 | `varchar` + 字典表 | 避免数据库原生 enum |', ''])

    lines.extend(['## 3. 逻辑数据模型', '', '### 3.1 实体清单', ''])
    lines.extend(render_entity_summary(entities))
    lines.extend(['', '### 3.2 实体关系图', '', '```mermaid', 'erDiagram'])
    if relations:
        for relation in relations:
            if relation['type'] == '1:1':
                edge = '||--||'
            elif relation['type'] == 'N:M':
                edge = '}o--o{'
            else:
                edge = '||--o{'
            lines.append(f'  {relation["from"]} {edge} {relation["to"]} : contains')
    else:
        lines.append('  %% 原型未提供可靠实体关系，关系待确认')
    lines.extend(['```', '', '### 3.3 关系说明', ''])
    lines.extend(render_relations(relations))

    lines.extend(['', '## 4. 物理表设计', ''])
    if entities:
        for index, entity in enumerate(entities, 1):
            lines.append(f'### 4.{index} {entity["table_name"]}（{entity["name"]}）')
            lines.append('')
            lines.append('| 属性 | 值 |')
            lines.append('|------|-----|')
            lines.append(f'| 表名 | `{cell(entity["table_name"])}` |')
            lines.append(f'| 中文名 | {cell(entity["name"])} |')
            lines.append(f'| 说明 | {cell(entity["description"])} |')
            lines.append(f'| 主键 | `{cell(entity["primary_key"])}` |')
            lines.append('')
            lines.append('| 序号 | 字段名 | 类型 | 长度 | 允许空 | 默认值 | 约束/索引 | 说明 |')
            lines.append('|------|--------|------|------|--------|--------|-----------|------|')
            for field_index, field in enumerate(entity['fields'], 1):
                flags = []
                if field['name'] == 'id':
                    flags.append('PK')
                if field['name'] in ('created_at', 'updated_at'):
                    flags.append('系统字段')
                lines.append(
                    f'| {field_index} | `{cell(field["name"])}` | {cell(field["type"])} '
                    f'| {cell(field["length"])} | '
                    f'{"否" if field["required"] == "是" else "是" if field["required"] == "否" else "待确认"} '
                    f'| {cell(field["default"])} | {cell(" / ".join(flags) or "-")} '
                    f'| {cell(field["description"])} |'
                )
            lines.append('')
            business_fields = [field for field in entity['fields']
                               if field['name'] not in ('id', 'created_at', 'updated_at')]
            if not business_fields:
                lines.append('> 原型未提取到明确业务字段，本表仅保留主键与审计字段，需业务方补充。')
                lines.append('')
            lines.append('**索引设计**')
            lines.append('')
            lines.append('| 索引名 | 类型 | 字段 | 说明 |')
            lines.append('|--------|------|------|------|')
            for index_item in entity['indexes']:
                lines.append(
                    f'| {cell(index_item["name"])} | {cell(index_item["type"])} '
                    f'| {cell(index_item["fields"])} | {cell(index_item["description"])} |'
                )
            lines.append('')
    else:
        lines.extend(['待补充（原型中未识别到可用字段）', ''])

    lines.extend(['## 5. 数据字典', ''])
    dictionary = {}
    for entity in entities:
        for field in entity['fields']:
            key = field['name']
            if key not in dictionary:
                dictionary[key] = {
                    'name': key,
                    'type': field['type'],
                    'length': field['length'],
                    'description': field['description'],
                    'tables': [entity['table_name']],
                }
            elif entity['table_name'] not in dictionary[key]['tables']:
                dictionary[key]['tables'].append(entity['table_name'])
    if dictionary:
        lines.append('| 字段名 | 类型 | 说明 | 所属表 |')
        lines.append('|--------|------|------|--------|')
        for item in dictionary.values():
            type_text = item['type']
            if item['length'] not in ('-', '', None):
                type_text += f'({item["length"]})'
            lines.append(
                f'| `{cell(item["name"])}` | {cell(type_text)} | {cell(item["description"])} '
                f'| {cell(item["tables"])} |'
            )
    else:
        lines.append('待补充。')

    lines.extend(['', '## 6. 索引与约束设计', '', '### 6.1 索引策略', '',
                  '高频查询字段建立普通索引；唯一业务标识建立唯一索引；组合索引遵循最左前缀原则。'
                  '当前索引均为基于页面字段的建议，需结合实际查询与数据量确认。',
                  '', '### 6.2 约束策略', '',
                  '主键非空唯一；业务唯一键由唯一索引保证；关联完整性由应用层校验。'
                  '原型未提供外键与级联策略，需在详细设计中确认。', ''])
    lines.extend(['## 7. 初始化与迁移', '', '### 7.1 初始化数据', '',
                  '- 字典表、系统配置等基础数据随版本初始化',
                  '- 管理员账号首次启动时创建', '',
                  '### 7.2 版本迁移', '',
                  '每次结构变更提供可回滚的迁移脚本，按版本号顺序执行。', ''])
    lines.extend(['## 8. 安全与权限', '', '### 8.1 数据安全', '',
                  '敏感字段加密存储，导出与查询遵循最小必要原则，操作留痕。', '',
                  '### 8.2 权限设计', '',
                  '按角色分配数据访问权限，应用账号仅授予必需的表级读写权限。', '',
                  '### 8.3 容量与备份', '',
                  '以下为默认基线（待确认）：', ''])
    lines.extend(render_nfr_table())
    lines.append('')
    lines.extend(render_appendix('database-design', data, pages, entities, skipped, version))
    return '\n'.join(lines)


def generate_document(data, doc_type, version='1.0.0', project_name=None):
    version = str(version).strip() or '1.0.0'
    if version.lower().startswith('v'):
        version = version[1:]
    pages = data.get('pages') or []
    if project_name:
        data = {**data, 'project_name': project_name}
    entities, skipped = build_entities(pages)
    if doc_type == 'system-overview':
        return render_system_overview(data, pages, entities, skipped, version)
    if doc_type == 'detailed-design':
        return render_detailed_design(data, pages, entities, skipped, version)
    if doc_type == 'database-design':
        return render_database_design(data, pages, entities, skipped, version)
    if doc_type == 'trial-run-report':
        return render_trial_run_report(data, pages, entities, skipped, version)
    if doc_type == 'maintenance-manual':
        return render_maintenance_manual(data, pages, entities, skipped, version)
    if doc_type == 'operation-manual':
        return render_operation_manual(data, pages, entities, skipped, version)
    if doc_type == 'application-inventory':
        return render_application_inventory(data, pages, entities, skipped, version)
    if doc_type == 'system-parameters':
        return render_system_parameters(data, pages, entities, skipped, version)
    if doc_type == 'training-plan':
        return render_training_plan(data, pages, entities, skipped, version)
    if doc_type == 'service-plan':
        return render_service_plan(data, pages, entities, skipped, version)
    if doc_type == 'test-report':
        return render_test_report(data, pages, entities, skipped, version)
    raise ValueError(f'不支持的文档类型：{doc_type}')


def main():
    parser = argparse.ArgumentParser(
        description='从原型解析 JSON 或 PRD Markdown 生成系统概要/详细/数据库设计/试运行/维护/操作/'
                    '软件清单/参数配置/培训计划/服务计划/功能与性能测试报告')
    parser.add_argument('json_path', help='parse_axure.py --json 输出的 JSON 文件，或 PRD Markdown 文件')
    parser.add_argument('output_path', nargs='?', help='输出 Markdown 路径')
    parser.add_argument('--doc-type', required=True, choices=sorted(DOC_TITLES),
                        help='文档类型')
    parser.add_argument('--prd', help='可选：PRD Markdown 路径，按 PRD 生成培训计划/服务计划/测试报告')
    parser.add_argument('--version', default='1.0.0', help='文档版本号（默认 1.0.0）')
    parser.add_argument('--project-name', help='覆盖输入数据中的项目名称')
    args = parser.parse_args()

    input_path = Path(args.json_path)
    if input_path.suffix.lower() in ('.md', '.markdown'):
        if args.doc_type not in PRD_BASED_DOC_TYPES:
            raise SystemExit('PRD Markdown 输入仅支持培训计划/服务计划/测试报告；'
                             '其他文档请传入 parse_axure.py --json 生成的 JSON')
        with open(input_path, 'r', encoding='utf-8') as file:
            try:
                data = parse_prd_markdown(file.read(), str(input_path))
            except ValueError as error:
                raise SystemExit(f'PRD 解析失败：{error}')
    else:
        with open(input_path, 'r', encoding='utf-8') as file:
            data = json.load(file)

    if args.prd:
        prd_path = Path(args.prd)
        if not prd_path.exists():
            raise SystemExit(f'PRD 文件不存在：{prd_path}')
        with open(prd_path, 'r', encoding='utf-8') as file:
            try:
                prd_data = parse_prd_markdown(file.read(), str(prd_path))
            except ValueError as error:
                raise SystemExit(f'PRD 解析失败：{error}')
        data = merge_prd_context(data, prd_data)

    pages = data.get('pages') or []
    if not pages:
        print('警告: 输入数据中没有 pages，生成内容将大量标注“待补充”', file=sys.stderr)

    content = generate_document(data, args.doc_type, args.version, args.project_name)
    output_path = args.output_path or DEFAULT_OUTPUTS[args.doc_type]

    # 规范化并校验输出路径，仅允许写入当前工作目录内，防止路径穿越
    base = os.path.realpath(os.getcwd())
    output_path = os.path.realpath(output_path)
    if output_path != base and not output_path.startswith(base + os.sep):
        raise SystemExit(f'输出路径越界，仅允许写入当前工作目录内：{output_path}')
    os.makedirs(os.path.dirname(output_path) or base, exist_ok=True)
    Path(output_path).write_text(content, encoding='utf-8')

    entities, _ = build_entities(pages)
    print(f'✓ 已生成 {output_path}（{len(pages)} 页面 / {len(entities)} 实体）')


if __name__ == '__main__':
    main()
