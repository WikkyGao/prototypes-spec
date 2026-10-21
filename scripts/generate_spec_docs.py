#!/usr/bin/env python3
"""从原型解析数据生成系统概要说明书、详细说明书、数据库设计说明书。

用法：
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type system-overview
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type detailed-design
    python3 scripts/generate_spec_docs.py <解析JSON> [输出路径] --doc-type database-design

输入：parse_axure.py --json 输出的 JSON 文件路径
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
}

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


def render_doc_frontmatter(project_name, version, doc_title):
    today = datetime.date.today().isoformat()
    return '\n'.join([
        f'# {project_name} {doc_title}',
        '',
        f'> 版本: v{version} | 更新日期: {today} | 文档类型: {doc_title}',
        '',
    ])


def render_intro(project_name, doc_title, pages, tool, root_path):
    page_names = [page.get('pageName') or '未命名页面' for page in pages]
    if not page_names:
        scope = '原型中未识别到可访问页面，适用范围待补充。'
    elif len(page_names) <= 12:
        scope = f'覆盖原型中的 {len(pages)} 个页面：{as_text(page_names)}'
    else:
        scope = f'覆盖原型中的 {len(pages)} 个页面，包括 {as_text(page_names[:12])} 等页面'
    glossary = [
        ('原型', '原型工具导出的 HTML/Schema 页面集合'),
        ('页面', '原型中的一个可访问页面或画板'),
        ('字段', '页面中出现的标签、控件或表格列推断出的数据项'),
        ('P0/P1/P2', '功能优先级：P0 核心、P1 重要、P2 一般'),
        ('待确认', '原型未体现、需业务方/开发/DBA 确认的内容'),
    ]
    purposes = {
        '系统概要说明书': f'本文档用于说明 {project_name} 的建设目标、总体架构、功能范围与非功能要求，作为设计评审、开发实现、测试验收与上线运维的依据。',
        '详细说明书': f'本文档用于说明 {project_name} 各模块的功能构成、处理流程、交互规则与异常处理，作为开发实现、联调与测试验收的依据。',
        '数据库设计说明书': f'本文档用于说明 {project_name} 的数据库选型、逻辑模型、物理表结构与索引设计，作为开发与 DBA 建库建表的依据。',
    }
    purpose = purposes.get(doc_title, f'本文档用于说明 {project_name} 的{doc_title}相关内容。')
    lines = ['## 1. 引言', '', '### 1.1 编写目的', '', purpose, '',
             '### 1.2 适用范围', '', scope, '']
    lines.extend(['### 1.3 术语与缩略语', '', '| 术语 | 说明 |', '|------|------|'])
    for term, definition in glossary:
        lines.append(f'| {cell(term)} | {cell(definition)} |')
    lines.extend(['', '### 1.4 参考资料', ''])
    lines.append(f'- 原型解析工具：{as_text(tool, "未知")}')
    lines.append(f'- 原型根目录：{as_text(root_path, "未提供")}')
    lines.append(f'- 页面数量：{len(pages)}')
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
    notes_included = any(page.get('notes') for page in pages)
    ambiguous = []
    for page in pages:
        for field in page.get('ambiguous_fields') or []:
            label = clean_label(field.get('label'))
            if label and not is_noise_label(label):
                ambiguous.append(f'{page.get("pageName")}「{label}」')
    lines = ['### 数据来源说明', '']
    lines.append(f'- 解析工具：{as_text(data.get("tool"), "未知")}')
    lines.append(f'- 原型目录：{as_text(data.get("root_path"), "未提供")}')
    lines.append(f'- 覆盖页面：{len(pages)} 个')
    if entities:
        lines.append(f'- 推断实体：{len(entities)} 个（表名、字段名、类型、索引均为建议，需后端/DBA 确认）')
    if skipped:
        lines.append(f'- 未纳入表设计的页面：{as_text(skipped)}')
    note_targets = {
        'system-overview': '功能描述、功能边界或待确认项',
        'detailed-design': '业务规则、交互步骤或待确认项',
        'database-design': '字段说明、索引建议或待确认项',
    }
    if notes_included:
        lines.append(f'- 便签/矩形内备注说明已纳入{note_targets.get(doc_type, "功能描述或待确认项")}')
    else:
        lines.append('- 未发现便签/矩形内备注说明')
    if ambiguous:
        lines.append(f'- 模糊字段 {len(ambiguous)} 个，需先确认：{as_text(ambiguous[:10])}')
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
    if not entities:
        pending.append('原型未识别到可用字段，实体与表设计待补充')
    if doc_type == 'database-design':
        pending.append('表名、字段名、字段类型、长度、索引均为原型推断建议，需后端与 DBA 最终确认')
        pending.append('原型未提供分库分表、数据量、备份与合规要求，需补充后再定稿')
    elif doc_type == 'detailed-design':
        pending.append('接口请求/响应结构、错误码、权限矩阵需后端与前端补充')
    else:
        pending.append('业务背景、建设目标、技术栈、部署方式原型未体现，需业务方补充')
    if skipped:
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
    raise ValueError(f'不支持的文档类型：{doc_type}')


def main():
    parser = argparse.ArgumentParser(
        description='从原型解析 JSON 生成系统概要说明书/详细说明书/数据库设计说明书')
    parser.add_argument('json_path', help='parse_axure.py --json 输出的 JSON 文件')
    parser.add_argument('output_path', nargs='?', help='输出 Markdown 路径')
    parser.add_argument('--doc-type', required=True, choices=sorted(DOC_TITLES),
                        help='文档类型')
    parser.add_argument('--version', default='1.0.0', help='文档版本号（默认 1.0.0）')
    parser.add_argument('--project-name', help='覆盖解析 JSON 中的项目名称')
    args = parser.parse_args()

    with open(args.json_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
    pages = data.get('pages') or []
    if not pages:
        print('警告: 解析 JSON 中没有 pages，生成内容将大量标注“待补充”', file=sys.stderr)

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
