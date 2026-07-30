#!/usr/bin/env python3
"""
Axure RP HTML 原型解析器
从 Axure 导出的 HTML 目录中提取页面结构、控件内容、交互事件等信息。
"""

import json
import os
import re
import sys
import argparse
import glob as _glob
from collections import Counter, defaultdict
from html.parser import HTMLParser


class AxurePageHTMLParser(HTMLParser):
    """解析 Axure 页面 HTML，提取文本内容、控件信息和便签/备注说明。"""

    def __init__(self):
        super().__init__()
        self.texts = []
        self.current_text = []
        self.in_span = False
        self.title = ""
        self.in_title = False
        self.widget_comments = []  # [{name, type}]
        # 便签/备注说明相关
        self.notes = []           # 便签/备注文本列表（Axure 中以 _ann 后缀标识）
        self.current_note = []    # 当前便签文本缓冲
        self.in_note = False      # 是否在便签 div 内
        self.in_note_span = False # 是否在便签内的 span 中
        # 矩形内备注说明（Axure 中"备注"字样的矩形/文本段落）
        self.rectangle_notes = [] # 矩形内备注说明文本列表
        self.current_rect_note = []
        self.in_rect_note_span = False
        self.rect_note_depth = 0
        # 截图拼接识别
        self.images = []            # [{src, width, height, style}]
        self.bg_images = []         # 重复 background-image 切片
        self.abs_positioned_count = 0  # 绝对定位元素计数
        # 表单/筛选区域识别
        self.form_field_labels = []  # 页面上出现的字段标签（按顺序）

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get('id', '')
        classes = attrs_dict.get('class', '')
        style = attrs_dict.get('style', '') or ''

        # 截图拼接识别：累计绝对定位元素
        if 'absolute' in style.lower():
            self.abs_positioned_count += 1

        # 截图拼接识别：收集 <img>
        if tag == 'img':
            self._track_image(attrs_dict)
            return

        # 截图拼接识别：background-image 切片
        bg_match = re.search(r'background(?:-image)?\s*:\s*url\(([^)]+)\)',
                             style, re.IGNORECASE)
        if bg_match:
            self.bg_images.append(bg_match.group(1))

        if tag == 'title':
            self.in_title = True
        elif tag == 'span':
            self.in_span = True
            self.current_text = []
            # 便签内的 span
            if self.in_note:
                self.in_note_span = True
                self.current_note = []
            # 矩形备注 span（处于 rect_note 上下文中）
            if self.in_rect_note_span is False and self.rect_note_depth > 0:
                self.in_rect_note_span = True
                self.current_rect_note = []
        elif tag == 'div':
            # 便签 div：id 以 _ann 结尾
            if element_id.endswith('_ann'):
                self.in_note = True
                self.current_note = []
            # 便签内嵌的子 div（不再单独开便签上下文）
            if self.in_note:
                return
            # 识别"备注"矩形：通过含"备注"类名或便签外链接的矩形
            # Axure 便签外矩形备注说明通常在 widget div 中含文本"备注"或注释含"备注"
            # 这里宽松采集：矩形控件（注释含"矩形"或 class 含 rect）内的 span 文本若以"备注:"/"备注："开头则视为矩形备注
            # 标记 rect_note_depth 进入矩形控件层
            if '备注' in element_id or 'note' in element_id.lower() or '_ann' in element_id:
                self.rect_note_depth += 1

    def _track_image(self, attrs_dict):
        """收集 <img> 元素用于截图拼接识别。"""
        src = attrs_dict.get('src', '') or ''
        width = attrs_dict.get('width', '') or ''
        height = attrs_dict.get('height', '') or ''
        style = attrs_dict.get('style', '') or ''
        self.images.append({
            'src': src, 'width': width, 'height': height, 'style': style,
        })

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag == 'span':
            text = ''.join(self.current_text).strip()
            if text:
                self.texts.append(text)
                # 矩形备注识别：文本以"备注"开头（含全角冒号变体）视为矩形内备注说明
                if re.match(r'^备注[:：]?\s*', text):
                    self.rectangle_notes.append(text)
            self.current_text = []
            self.in_span = False

            # 便签 span 结束
            if self.in_note_span:
                note_text = ''.join(self.current_note).strip()
                if note_text:
                    self.current_note_text = note_text  # 暂存，等便签 div 结束再归并
                self.in_note_span = False
                self.current_note = []

            # 矩形备注 span 结束
            if self.in_rect_note_span:
                rect_text = ''.join(self.current_rect_note).strip()
                if rect_text and not re.match(r'^备注[:：]?\s*', rect_text):
                    # 矩形内非"备注"标题的文本，若是备注说明的正文，追加到上一条 rectangle_note
                    if self.rectangle_notes:
                        self.rectangle_notes[-1] = self.rectangle_notes[-1] + ' ' + rect_text
                self.in_rect_note_span = False
                self.current_rect_note = []
        elif tag == 'div':
            if self.in_note:
                # 便签 div 结束时归并文本
                # 通过 attrs 无法在 endtag 拿到 id，用缓冲法：便签内所有 span 文本合并
                # 这里简化：便签文本已在 span 处理中暂存，div 结束时统一收尾
                pass
            if self.rect_note_depth > 0:
                self.rect_note_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_span:
            self.current_text.append(data)
        if self.in_note_span:
            self.current_note.append(data)
        if self.in_rect_note_span:
            self.current_rect_note.append(data)

    def handle_comment(self, data):
        # 解析控件注释: <!-- Unnamed (矩形) --> 或 <!-- 名称 (按钮) -->
        match = re.match(r'\s*(.*?)\s*\((.+?)\)\s*', data)
        if match:
            widget_name = match.group(1).strip()
            widget_type = match.group(2).strip()
            self.widget_comments.append({
                'name': widget_name if widget_name != 'Unnamed' else '',
                'type': widget_type
            })

    def get_notes(self):
        """提取便签/备注说明文本列表。

        Axure 中便签（Annotation）以 id 后缀 _ann 的 div 标识，
        其文本在 span 内。本方法在解析完成后从 texts 中识别
        便签来源的文本（通过 id 关联），并合并矩形内备注说明。

        由于 HTMLParser 流式解析不便保留 id 关联，这里采用后置筛选：
        - rectangle_notes：已显式采集的矩形内备注说明
        - texts 中含"备注:"/"备注："开头的文本已被归入 rectangle_notes
        - 便签 _ann 的文本作为 notes 单独返回需在解析时标记，简化为：
          将 rectangle_notes + 便签特征文本合并返回
        """
        notes = list(self.rectangle_notes)
        # 便签文本通常较短且独立，此处可补充识别（如 texts 中明确的备注条目）
        # 去重并保留顺序
        seen = set()
        merged = []
        for n in notes:
            if n not in seen:
                merged.append(n)
                seen.add(n)
        return merged


# ---------------------------------------------------------------------------
# 页面分类（page category）
# ---------------------------------------------------------------------------

# 页面分类标签：扩展时可在此补充
PAGE_CATEGORIES = [
    'admin_console',      # 管理后台页面（左侧菜单+表格+筛选区+分页）
    'config_page',        # 配置页（表单为主，含保存/重置）
    'mobile_page',        # 移动端页面（窄屏 viewport / 手机外框）
    'flow_diagram',       # 流程图 / 拓扑图（纯图形/连线，无表单）
    'login_page',         # 登录 / 注册 / 验证码页
    'list_page',          # 列表页（表格 / 卡片列表）
    'detail_page',        # 详情页（标题 + 字段键值对）
    'form_page',          # 表单页（输入控件为主）
    'modal_dialog',       # 弹窗 / 对话框
    'dashboard',          # 仪表盘 / 数据看板
    'image_composite',    # 截图拼接页（由多张截图拼出来）
    'unknown',            # 无法判定
]

# 分类识别关键词字典：中文 + 英文，用于匹配页面名 / 文本内容
_CATEGORY_KEYWORDS = {
    'login_page': [
        '登录', '登陆', '注册', '验证码', '找回密码', '忘记密码',
        'login', 'register', 'signin', 'sign in', 'signup', 'sign up',
    ],
    'admin_console': [
        '管理后台', '后台管理', '运营后台', '系统管理', '控制台',
        'admin', 'console', 'backstage',
    ],
    'config_page': [
        '配置', '设置', '参数设置', '系统设置', '规则配置',
        'config', 'setting', 'preference',
    ],
    'mobile_page': [
        '移动端', '手机端', 'app端', 'h5',
        'mobile', 'viewport',
    ],
    'flow_diagram': [
        '流程图', '流程', '拓扑', '节点', '连线',
        'flowchart', 'topology',
    ],
    'dashboard': [
        '仪表盘', '看板', '大盘', '首页', 'dashboard', 'overview',
    ],
}

# 控件类型 → 推断的页面分类（当文本匹配不足时按控件组合判断）
def _infer_category_from_widgets(widgets):
    widget_types = [w.get('type', '') or w.get('friendlyType', '')
                    for w in widgets]
    type_set = set(widget_types)

    # 表格 + 分页 + 下拉筛选 → 管理后台
    has_table = any('表格' in t or 'table' in t.lower() for t in widget_types)
    has_dropdown = any('下拉' in t or 'dropdown' in t.lower()
                       for t in widget_types)
    has_button = any('按钮' in t or 'button' in t.lower()
                     for t in widget_types)
    has_input = any('输入框' in t or '文本框' in t
                    or 'input' in t.lower() or 'textarea' in t.lower()
                    for t in widget_types)
    has_img = any('图片' in t or 'image' in t.lower() or 'img' in t.lower()
                  for t in widget_types)

    if has_table and (has_dropdown or has_button):
        return 'admin_console'
    if has_img and not has_input and not has_table:
        return 'flow_diagram'
    if has_input and not has_table:
        return 'form_page'
    if has_table and not has_dropdown:
        return 'list_page'
    return None


def classify_page(page):
    """
    根据页面名、文本、控件推断页面分类。

    返回 PAGE_CATEGORIES 中的一个标签。
    优先级：截图拼接识别 > 关键词匹配 > 控件推断 > unknown
    """
    page_name = page.get('pageName', '') or ''
    texts = page.get('texts', []) or []
    widgets = page.get('widgets', []) or []
    text_blob = ' '.join(texts)
    name_blob = page_name

    # 1) 关键词匹配：同时考虑页面名和文本
    matches = []
    for cat, kws in _CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw in name_blob or kw in text_blob:
                matches.append(cat)
                break
    # 取匹配数最多的一类；若多个并列，admin_console > config_page > 其他
    if matches:
        priority = ['admin_console', 'config_page', 'mobile_page',
                    'flow_diagram', 'login_page', 'dashboard']
        for p in priority:
            if p in matches:
                return p
        return matches[0]

    # 2) 控件推断
    inferred = _infer_category_from_widgets(widgets)
    if inferred:
        return inferred

    # 3) 截图拼接（由调用方先标记 page['is_screenshot_composite']）
    if page.get('is_screenshot_composite'):
        return 'image_composite'

    return 'unknown'


# ---------------------------------------------------------------------------
# 全局菜单壳噪声过滤
# ---------------------------------------------------------------------------

def build_menu_noise_set(pages):
    """
    从页面 texts 中提取全局菜单噪声集。

    策略：找出现次数最多的前 150 条文本，对大多数页面 (>80%) 都出现的文本即为菜单噪声。
    Axure 导出后每个页面 HTML 的开头 ~135 条 <span> 是全局菜单文本（完全相同），
    导致 page['texts'] 被大量噪声污染。

    返回: set[str] 噪声文本集合
    """
    text_counter = Counter()
    for page in pages:
        # 取每个页面前 200 条去重文本（菜单壳在前）
        unique = []
        for t in page.get('texts', []):
            if t not in unique:
                unique.append(t)
                if len(unique) >= 200:
                    break
        text_counter.update(unique)

    total = len(pages)
    if total == 0:
        return set()
    threshold = int(total * 0.8)
    noise = {t for t, c in text_counter.items() if c >= threshold and len(t) >= 1}
    return noise


# ---------------------------------------------------------------------------
# 截图拼接识别
# ---------------------------------------------------------------------------

def detect_screenshot_composite(parser, texts):
    """
    判断页面是否由截图拼接而成。

    识别特征（满足任一即判定为拼接截图）：
      - 页面含多个 <img>，且至少一张宽度 >= 600px 或 style 含大尺寸
      - 多张 background-image 切片（>= 2 个不同 url）
      - 文本内容极少（<= 5 条）且图片数 >= 3
      - 全部内容只有一张超大图（width >= 800）且几乎没有 span 文本

    参数:
        parser: AxurePageHTMLParser 实例（含 images/bg_images）
        texts:  页面 span 文本列表

    返回:
        (is_composite: bool, evidence: str)
    """
    images = parser.images
    bg_images = parser.bg_images
    text_count = len(texts)

    # 多张大图
    big_imgs = []
    for img in images:
        w = img.get('width', '') or ''
        h = img.get('height', '') or ''
        style = img.get('style', '') or ''
        # 从 width 属性
        try:
            wi = int(re.match(r'(\d+)', w).group(1)) if w else 0
        except (AttributeError, ValueError):
            wi = 0
        # 从 style width
        if wi == 0:
            m = re.search(r'width\s*:\s*(\d+)', style, re.IGNORECASE)
            if m:
                wi = int(m.group(1))
        if wi >= 600:
            big_imgs.append(img)

    # 多张 background-image 切片（不同 url）
    unique_bg = set()
    for bg in bg_images:
        # 去除查询参数后比较
        base = bg.split('?')[0]
        unique_bg.add(base)

    # 条件 1：多张大图（>=2 张宽度 >=600）
    if len(big_imgs) >= 2:
        return True, f"检测到 {len(big_imgs)} 张大尺寸图片(宽>=600px)，疑似截图拼接"

    # 条件 2：多张不同 background-image 切片
    if len(unique_bg) >= 2:
        return True, f"检测到 {len(unique_bg)} 个不同的 background-image 切片，疑似截图拼接"

    # 条件 3：文本极少 + 图片数 >= 3
    if text_count <= 5 and len(images) >= 3:
        return True, f"文本仅 {text_count} 条但图片 {len(images)} 张，疑似截图拼接"

    # 条件 4：单张超大图 + 几乎无文本
    for img in images:
        w = img.get('width', '') or ''
        try:
            wi = int(re.match(r'(\d+)', w).group(1)) if w else 0
        except (AttributeError, ValueError):
            wi = 0
        style = img.get('style', '') or ''
        if wi == 0:
            m = re.search(r'width\s*:\s*(\d+)', style, re.IGNORECASE)
            if m:
                wi = int(m.group(1))
        if wi >= 800 and text_count <= 5:
            return True, f"检测到一张 {wi}px 宽的超大图且文本仅 {text_count} 条，疑似截图拼接"

    return False, ''


# ---------------------------------------------------------------------------
# 筛选区域识别（管理后台常见）
# ---------------------------------------------------------------------------

# 筛选区常见关键词：中文 + 英文
_FILTER_AREA_KEYWORDS = [
    '筛选', '过滤', '查询条件', '搜索条件', '查询', '检索',
    'filter', 'search', 'query',
]

# 筛选区常见操作按钮
_FILTER_ACTION_KEYWORDS = [
    '查询', '搜索', '筛选', '重置', '清空',
    'search', 'filter', 'reset', 'clear',
]

# 常见筛选字段名后缀（用于识别字段标签）
_FILTER_FIELD_HINTS = [
    '名称', '编号', '状态', '时间', '日期', '类型', '分类', '部门',
    '创建时间', '更新时间', '手机', '邮箱', '地区', '标签', '级别',
]


def detect_filter_area(parser, texts, widgets):
    """
    识别管理后台页面的筛选区域。

    筛选区识别逻辑：
      1) 文本中含筛选关键词（筛选/查询/搜索条件等）
      2) 或文本中含筛选操作按钮（查询/搜索/重置/清空）且同时存在下拉框/输入框
      3) 字段标签：从 texts 中按出现顺序提取，匹配 _FILTER_FIELD_HINTS 的优先纳入

    返回:
        {
            'has_filter': bool,
            'filter_fields': [{label, control_type, required, default_value, note}],
            'filter_actions': [str],   # 查询/重置等按钮
        }
    """
    text_blob = ' '.join(texts)

    has_filter_kw = any(kw in text_blob for kw in _FILTER_AREA_KEYWORDS)
    has_action_kw = any(kw in text_blob for kw in _FILTER_ACTION_KEYWORDS)

    # 控件类型收集
    widget_types = [w.get('type', '') or w.get('friendlyType', '')
                    for w in widgets]
    has_dropdown = any('下拉' in t or 'dropdown' in t.lower()
                       for t in widget_types)
    has_input = any('输入框' in t or '文本框' in t
                    or 'input' in t.lower() or 'textarea' in t.lower()
                    for t in widget_types)
    has_date = any('日期' in t or 'date' in t.lower()
                   for t in widget_types)

    # 判定是否存在筛选区
    has_filter = False
    if has_filter_kw and (has_dropdown or has_input or has_date):
        has_filter = True
    elif has_action_kw and (has_dropdown or has_input or has_date):
        has_filter = True

    if not has_filter:
        return {
            'has_filter': False,
            'filter_fields': [],
            'filter_actions': [],
        }

    # 提取筛选字段：按 texts 出现顺序，匹配 HINTS 或位于筛选关键词前后的标签
    filter_fields = []
    seen_labels = set()
    for t in texts:
        # 跳过按钮文字/操作文字
        if t in _FILTER_ACTION_KEYWORDS or t in _FILTER_AREA_KEYWORDS:
            continue
        # 匹配字段提示后缀
        is_field_label = any(t.endswith(hint) or hint in t
                              for hint in _FILTER_FIELD_HINTS)
        # 短文本（<=10 字符）且以"："或":"结尾也视为字段标签
        ends_with_colon = t.endswith('：') or t.endswith(':')
        if (is_field_label or ends_with_colon) and t not in seen_labels:
            filter_fields.append({
                'label': t,
                'control_type': '待确认',     # 不臆想，从页面控件对应
                'required': '待确认',
                'default_value': '待确认',
                'note': '从页面文本提取的字段标签，控件类型/必填/默认值需对照原型确认',
            })
            seen_labels.add(t)

    # 提取筛选操作按钮
    filter_actions = [t for t in texts if t in _FILTER_ACTION_KEYWORDS]
    # 去重保持顺序
    seen_actions = set()
    dedup_actions = []
    for a in filter_actions:
        if a not in seen_actions:
            dedup_actions.append(a)
            seen_actions.add(a)

    return {
        'has_filter': True,
        'filter_fields': filter_fields,
        'filter_actions': dedup_actions,
    }


# ---------------------------------------------------------------------------
# 字段说明严格基于页面出现内容（禁止臆想）
# ---------------------------------------------------------------------------

def _is_data_value(text, page_texts):
    """
    判断一个文本片段是数据值而非字段标签。

    特征：含数字/IP/人名特征、在页面重复出现、无冒号结尾。
    """
    # 以 ： 或 : 结尾 → 字段标签，非数据值
    if text.endswith('：') or text.endswith(':'):
        return False
    # 含 IP 地址
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', text):
        return True
    # 纯数字（含端口、数量、百分比）
    if re.match(r'^[\d.,]+[%％]?$', text.strip()):
        return True
    # 含 UUID 或哈希
    if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-', text):
        return True
    # 中文人名特征：2-3个中文字 + 在页面重复 ≥2 次
    if re.match(r'^[一-龥]{2,3}$', text):
        count = page_texts.count(text)
        if count >= 2:
            return True
    # 含常见数据值后缀（元、个、台、次、项等数量单位）且以数字开头
    if re.match(r'^\d+[元个台次项人件条张颗只块]', text):
        return True
    return False


def extract_page_fields_strict(texts, widgets, page_name=''):
    """
    严格基于页面可见内容提取字段说明，禁止凭空臆想。

    提取规则：
      - 字段标签必须出现在页面 texts 中（不臆想）
      - 字段类型从对应控件类型推断（下拉/输入框/日期/单选/复选），
        若无控件对应则标注"待确认"
      - 必填/默认值/校验规则若原型未明确显示，一律标"待确认"，
        不得凭空臆想
      - 遇到模糊字段（如标签后无控件、控件无标签），归入 ambiguous_fields，
        需要先和用户确认再写入 PRD/数据字典

    返回:
        {
            'fields': [{name, label, type, required, default_value, note, source}],
            'ambiguous_fields': [{label, reason, suggested_type}],
        }
    """
    # 控件类型清单
    widget_types = [w.get('type', '') or w.get('friendlyType', '')
                    for w in widgets]
    has_dropdown = any('下拉' in t for t in widget_types)
    has_date = any('日期' in t or 'date' in t.lower()
                   for t in widget_types)
    has_radio = any('单选' in t for t in widget_types)
    has_checkbox = any('复选' in t for t in widget_types)
    has_input = any('输入框' in t or '文本框' in t
                    or 'input' in t.lower() for t in widget_types)

    fields = []
    ambiguous_fields = []
    seen_labels = set()

    for idx, t in enumerate(texts):
        # 跳过数据值（IP地址、纯数字、人名等）
        if _is_data_value(t, texts):
            continue
        # 字段标签特征：以":"或"："结尾，或匹配常见字段后缀
        ends_with_colon = t.endswith('：') or t.endswith(':')
        matches_hint = any(hint in t for hint in _FILTER_FIELD_HINTS)
        if not (ends_with_colon or matches_hint):
            continue
        # 跳过操作按钮/筛选关键词
        if t in _FILTER_ACTION_KEYWORDS or t in _FILTER_AREA_KEYWORDS:
            continue

        label = t
        # 推断控件类型：若该标签后紧跟"请选择"则下拉，"请输入"则输入框
        next_text = texts[idx + 1] if idx + 1 < len(texts) else ''
        control_type = '待确认'
        if next_text:
            if '请选择' in next_text or '请选择' in next_text:
                control_type = '下拉选择(dropdown)'
            elif '请输入' in next_text or '请填写' in next_text:
                control_type = '输入框(input)'
            elif '请选择日期' in next_text or '选择日期' in next_text:
                control_type = '日期选择器(date picker)'

        # 全局控件类型补判
        if control_type == '待确认':
            if has_dropdown and not has_input:
                control_type = '下拉选择(dropdown)（推测，需确认）'
            elif has_date and any('时间' in label or '日期' in label
                                   for _ in [0]):
                control_type = '日期选择器(date picker)（推测，需确认）'

        if label in seen_labels:
            continue
        seen_labels.add(label)

        field_info = {
            'name': '',  # 英文字段名需用户/后端确认，不臆想
            'label': label,
            'type': control_type,
            'required': '待确认',      # 原型未明确 * 必填符号时不得假设
            'default_value': '待确认', # 原型未显示默认值时不得假设
            'note': '字段标签来源于页面文本，类型/必填/默认值需对照原型确认',
            'source': 'page_text',
        }

        # 模糊字段：标签后无对应控件文本，或类型完全无法推断
        if control_type == '待确认':
            ambiguous_fields.append({
                'label': label,
                'reason': '未在页面找到对应控件类型，无法确定是输入框/下拉/日期等',
                'suggested_type': '待用户确认',
            })

        fields.append(field_info)

    return {
        'fields': fields,
        'ambiguous_fields': ambiguous_fields,
    }


# ---------------------------------------------------------------------------
# 表格列头提取（Axure 中继器表格）
# ---------------------------------------------------------------------------

def extract_table_columns_from_html(html_content):
    """
    从 Axure HTML 中提取表格列头。
    策略：找 y 坐标在 5~30 范围内、元素数量最多的几行，按 x 坐标排序去重。
    返回: [(column_name, x_position), ...]
    """
    divs = re.findall(
        r'<div[^>]*data-left="(\d+)"[^>]*data-top="(\d+)"[^>]*>.*?<span[^>]*>([^<]+)</span>',
        html_content, re.DOTALL
    )

    y_groups = defaultdict(list)
    for x, y, text in [(int(d[0]), int(d[1]), d[2].strip()) for d in divs]:
        if text and len(text) >= 2 and 5 <= y <= 30:
            y_groups[y].append((int(x), text))

    # 取元素 ≥4 且 y≤20 的行作为候选表头行
    candidate_rows = []
    for y, items in y_groups.items():
        if len(items) >= 4 and y <= 20:
            items.sort(key=lambda i: i[0])
            candidate_rows.append((y, len(items), items))

    if not candidate_rows:
        return []

    # 取元素最多的行作为主表头行，与其相邻 y (±3) 的行做补全
    candidate_rows.sort(key=lambda r: r[1], reverse=True)
    main_y = candidate_rows[0][0]

    all_columns = {}  # {x_pos: column_name}
    for y, _, items in candidate_rows:
        if abs(y - main_y) <= 3:  # 临近行纳入
            for x, text in items:
                if x not in all_columns:
                    all_columns[x] = text

    result = [(text, x) for x, text in sorted(all_columns.items(), key=lambda i: i[0])]

    # 去重（相同文本只保留最小的 x 坐标）
    seen = set()
    dedup = []
    for text, x in result:
        if text not in seen:
            seen.add(text)
            dedup.append((text, x))

    return dedup


def _parse_rootnodes_stream(filepath):
    """
    从 document.js 的 rootNodes 数据流中提取页面序列。

    rootNodes 段的字符串值顺序流（仅取 ="..." 形式的字符串值）：
      显式 key 模式（首条页面）：
        'id', <id>, 'pageName', <name>, 'type', <type>, 'url', <url.html>
      隐式模式（后续页面）：
        <id>, <name>, <type|'Folder'>, <url.html>
      Folder 节点（无 url，type 值为 'Folder'）：
        <id>, <name>, 'Folder'
      children 关键字引导嵌套数组。

    本函数不依赖任何硬编码页面名，仅基于 'pageName'/'type'/'url'/'Folder'/'children'
    等结构标记和 .html 后缀解析。

    返回 (pages, raw_values)：
      pages: [{name, url, is_folder}] 按出现顺序排列
      raw_values: rootNodes 段内所有 ="..." 字符串值（供深度推断）
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    root_idx = content.find('rootNodes')
    if root_idx < 0:
        return [], []

    chunk = content[root_idx:root_idx + 50000]
    values = re.findall(r'="([^"]*)"', chunk)

    # 终止标记：rootNodes 页面区结束后进入这些配置节
    terminal_markers = {
        'additionalJs', 'additionalCss', 'globalVariables',
        'stylesheet', 'defaultStyle',
    }

    pages = []
    i = 0
    n = len(values)
    while i < n:
        v = values[i]

        # 命中终止标记，停止扫描
        if v in terminal_markers and pages:
            break

        # 显式 key 模式：'id', <id>, 'pageName', <name>, 'type', <type>, 'url', <url.html>
        if (v == 'id' and i + 7 < n
                and values[i+2] == 'pageName'
                and values[i+4] == 'type'
                and values[i+6] == 'url'):
            name = values[i+3]
            is_folder = (values[i+5] == 'Folder')
            url = values[i+7]
            pages.append({'name': name, 'url': url, 'is_folder': is_folder})
            i += 8
            continue

        # 隐式三元模式：<id>, <name>, <url.html>
        if i + 2 < n and values[i+2].endswith('.html'):
            pages.append({'name': values[i+1], 'url': values[i+2],
                          'is_folder': False})
            i += 3
            continue

        # 隐式 Folder 模式：<id>, <name>, 'Folder'
        if i + 2 < n and values[i+2] == 'Folder':
            pages.append({'name': values[i+1], 'url': '',
                          'is_folder': True})
            i += 3
            continue

        i += 1

    return pages, values


def build_page_tree(filepath):
    """
    从 document.js 中提取页面树结构。

    直接基于 rootNodes 数据流解析，不依赖硬编码页面名。
    Axure 的页面层级通过 'children' 关键字嵌套表达；Folder 节点用 'Folder' 标识。

    返回页面列表，每项包含：{pageName, url, children, isFolder?}
    """
    pages, values = _parse_rootnodes_stream(filepath)
    if not pages:
        return []

    # 推断每个页面的深度
    # 策略：遍历 values，跟踪 'children' 嵌套与 'Folder' 标记
    # 简化模型：所有页面默认 depth=0；遇到 Folder 后的子页面 depth+1
    page_names_order = [p['name'] for p in pages]
    depths = [0] * len(pages)

    current_depth = 0
    folder_active = False
    last_folder_depth = 0
    page_idx = 0

    for v in values:
        # 页面名匹配（按出现顺序消费）
        if page_idx < len(pages) and v == pages[page_idx]['name']:
            if folder_active:
                depths[page_idx] = last_folder_depth + 1
            else:
                depths[page_idx] = current_depth
            page_idx += 1
            continue

        if v == 'children':
            current_depth += 1
            folder_active = False
        elif v == 'Folder':
            folder_active = True
            last_folder_depth = current_depth
        elif v in ('additionalJs', 'additionalCss', 'globalVariables',
                   'stylesheet', 'defaultStyle'):
            folder_active = False
            current_depth = 0

    # 根据深度构建树
    root = []
    stack = [root]  # stack[d] 是深度 d 的兄弟列表

    for idx, page in enumerate(pages):
        depth = depths[idx]

        # 弹栈到目标深度
        while len(stack) > depth + 1:
            stack.pop()
        # 补栈
        while len(stack) <= depth:
            stack.append([])

        node = {
            'pageName': page['name'],
            'url': page['url'],
            'children': []
        }
        if page['is_folder']:
            node['isFolder'] = True
        stack[depth].append(node)

    return root


def extract_pages_flat(filepath):
    """从 document.js 中提取扁平页面列表（不包含树结构）。"""
    pages, _ = _parse_rootnodes_stream(filepath)
    return [
        {'pageName': p['name'], 'url': p['url']}
        for p in pages
        if not p['is_folder'] and p['url'].endswith('.html')
    ]


def parse_page_html(filepath):
    """解析单个页面 HTML 文件，提取文本内容、控件信息、便签/备注说明，
    并附加：
      - is_screenshot_composite / screenshot_evidence：截图拼接识别
      - strict_fields / ambiguous_fields：严格基于页面内容的字段说明
      - filter_area：筛选区域识别（管理后台常见）
    分类（page_category）由 classify_page 统一在页面层推断。
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except (FileNotFoundError, IOError):
        return {
            'title': '', 'texts': [], 'widgets': [], 'notes': [],
            'is_screenshot_composite': False, 'screenshot_evidence': '',
            'strict_fields': [], 'ambiguous_fields': [],
            'filter_area': {'has_filter': False,
                             'filter_fields': [], 'filter_actions': []},
            'table_columns': [],
        }

    parser = AxurePageHTMLParser()
    parser.feed(html_content)

    texts = parser.texts
    widgets = parser.widget_comments

    # 截图拼接识别
    is_composite, evidence = detect_screenshot_composite(parser, texts)

    # 严格字段提取（禁止臆想）
    strict = extract_page_fields_strict(texts, widgets)

    # 筛选区域识别
    filter_area = detect_filter_area(parser, texts, widgets)

    # 表格列头提取
    table_columns = extract_table_columns_from_html(html_content)

    return {
        'title': parser.title,
        'texts': texts,
        'widgets': widgets,
        'notes': parser.get_notes(),
        'is_screenshot_composite': is_composite,
        'screenshot_evidence': evidence,
        'strict_fields': strict['fields'],
        'ambiguous_fields': strict['ambiguous_fields'],
        'filter_area': filter_area,
        'table_columns': table_columns,
    }


def parse_page_data_js(filepath):
    """
    解析 files/<页面名>/data.js，提取控件详细信息和交互事件。
    
    返回控件列表，每个控件包含：
    - id: 控件ID
    - label: 控件标签
    - friendlyType: 控件友好类型
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except (FileNotFoundError, IOError):
        return {'widgets': [], 'interactions': []}
    
    # 提取控件数据
    # 在压缩代码中查找：label、friendlyType 等字段
    # 提取所有 "label","value" 和 "friendlyType","value" 对
    labels = re.findall(r'"label","([^"]*)"', content)
    types = re.findall(r'"friendlyType","([^"]*)"', content)
    ids = re.findall(r'"id","([^"]+)"', content)
    
    # 交互事件
    interactions = []
    # onClick 事件
    click_descriptions = re.findall(r'"onClick"[^}]*"description","([^"]*)"', content)
    for desc in click_descriptions:
        interactions.append({'event': 'onClick', 'description': desc})
    
    # 其他交互
    for event_type in ['onMouseEnter', 'onMouseLeave', 'onLoad', 'onChange']:
        event_matches = re.findall(event_type + r'[^}]*"description","([^"]*)"', content)
        for desc in event_matches:
            interactions.append({'event': event_type, 'description': desc})
    
    # 控件类型映射
    type_map = {
        '矩形': 'rectangle',
        '按钮': 'button',
        '图片': 'image',
        '图片 ': 'image',
        '文本段落': 'text',
        '输入框': 'input',
        '文本框': 'textarea',
        '下拉列表': 'dropdown',
        '复选框': 'checkbox',
        '单选按钮': 'radio',
        '表格': 'table',
        '单元格': 'table_cell',
        '树': 'tree',
        '节点': 'tree_node',
        '动态面板': 'dynamic_panel',
        '中继器': 'repeater',
        '水平线': 'horizontal_line',
        '垂直线': 'vertical_line',
        '热区': 'hot_spot',
        '内联框架': 'inline_frame',
        '形状': 'shape',
    }
    
    widgets = []
    for i, (w_id, label, w_type) in enumerate(zip(ids, labels, types)):
        en_type = type_map.get(w_type, w_type)
        widgets.append({
            'id': w_id,
            'label': label,
            'friendlyType': w_type,
            'type_en': en_type,
        })
    
    return {'widgets': widgets, 'interactions': interactions}


def discover_page_html_files(directory_path):
    """扫描目录，发现所有页面 HTML 文件（排除框架文件）。"""
    html_files = []
    exclude_patterns = ['start.html', 'start_c_1.html', 'start_with_pages.html', 'index.html',
                        'remote.html', 'frame.html', 'main.html', 'preview.html']
    
    for f in os.listdir(directory_path):
        if f.endswith('.html') and f not in exclude_patterns:
            # 排除 resources/ 目录下的文件
            html_files.append(f)
    
    return sorted(html_files)


def detect_tool_type(directory_path):
    """
    识别原型工具类型。
    
    返回 'axure' / 'mockplus' / 'mastergo' / 'lanhu' / 'unknown'
    
    判定逻辑：
    - axure: 有 data/document.js 或 resources/scripts/axure/ 目录
    - mockplus: 有 mockplus 特征文件（mockplus.js / mp.js / 或 mockplus 字样在 index.html）
    - mastergo: 有 mastergo 离线标注特征（含 PAGED_FRAMES 或 FILE_DATA 的 .js 文件）
    - lanhu: 有蓝湖特征（含 lanhutext/lanhuimage/lanhubutton 的 JSON 或 .lanhu 文件）
    - unknown: 无法判定，退化为通用 HTML 解析
    """
    directory_path = os.path.abspath(directory_path)
    
    # Axure 判定
    if os.path.exists(os.path.join(directory_path, 'data', 'document.js')):
        return 'axure'
    if os.path.isdir(os.path.join(directory_path, 'resources', 'scripts', 'axure')):
        return 'axure'
    
    # 墨刀/Mockplus 判定
    # 墨刀离线包通常含 mockplus.js 或在 index.html 中有 mockplus 字样
    index_html = os.path.join(directory_path, 'index.html')
    if os.path.exists(index_html):
        try:
            with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                idx_content = f.read(5000)
            if 'mockplus' in idx_content.lower() or 'mp-' in idx_content.lower():
                return 'mockplus'
            if 'mastergo' in idx_content.lower():
                return 'mastergo'
            if 'lanhu' in idx_content.lower() or 'lanhuapp' in idx_content.lower():
                return 'lanhu'
        except (FileNotFoundError, IOError):
            pass
    
    # 检查目录中的特征文件
    for f in os.listdir(directory_path):
        lower = f.lower()
        if 'mockplus' in lower or f == 'mp.js':
            return 'mockplus'
        if 'mastergo' in lower:
            return 'mastergo'
        if 'lanhu' in lower:
            return 'lanhu'
    
    # 检查子目录中的 JS 文件内容特征（深度扫描）
    for root, dirs, files in os.walk(directory_path):
        # 限制深度，避免扫描过深
        depth = root[len(directory_path):].count(os.sep)
        if depth > 2:
            continue
        for f in files:
            if not f.endswith('.js'):
                continue
            try:
                with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as fh:
                    chunk = fh.read(3000)
                if 'PAGED_FRAMES' in chunk or 'FILE_DATA' in chunk:
                    return 'mastergo'
                if 'mockplus' in chunk.lower() or 'Mockplus' in chunk:
                    return 'mockplus'
                if 'lanhutext' in chunk or 'lanhuimage' in chunk or 'lanhubutton' in chunk:
                    return 'lanhu'
            except (FileNotFoundError, IOError):
                pass
        # 避免遍历 node_modules 等无关目录
        dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', 'resources')]
    
    return 'unknown'


def parse_mockplus_directory(directory_path):
    """
    解析墨刀离线 HTML 演示包。
    
    墨刀离线包结构：
    - index.html: 入口（含页面导航）
    - 各页面 HTML 文件
    - 资源目录（图片、脚本）
    
    策略：扫描所有 HTML 文件，提取文本内容，构建扁平页面列表。
    """
    directory_path = os.path.abspath(directory_path)
    
    result = {
        'type': 'mockplus_directory',
        'tool': 'mockplus',
        'root_path': directory_path,
        'project_name': os.path.basename(directory_path),
        'pages': [],
        'page_tree': [],
        'total_pages': 0,
    }
    
    # 扫描所有 HTML 文件（排除 index/frame 等）
    html_files = discover_page_html_files(directory_path)
    
    # 尝试从 index.html 提取页面树
    index_html = os.path.join(directory_path, 'index.html')
    if os.path.exists(index_html):
        try:
            with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                idx_content = f.read()
            # 墨刀 index.html 中可能有页面链接列表
            import re
            # 查找所有 href="xxx.html" 链接
            links = re.findall(r'href=["\']([^"\']+\.html)["\']', idx_content)
            # 去重并排除框架文件
            seen = set()
            for link in links:
                base = os.path.basename(link)
                if base not in seen and base not in ('index.html', 'remote.html', 'frame.html'):
                    seen.add(base)
                    if base not in html_files:
                        html_files.append(base)
        except (FileNotFoundError, IOError):
            pass
    
    # 解析每个页面
    for html_file in html_files:
        html_path = os.path.join(directory_path, html_file)
        page_name = html_file.replace('.html', '')
        
        html_data = parse_page_html(html_path)

        page_info = {
            'pageName': page_name,
            'url': html_file,
            'texts': html_data['texts'],
            'widgets': html_data['widgets'],
            'notes': html_data.get('notes', []),
            'has_html': True,
            'has_data_js': False,
            'is_screenshot_composite': html_data.get('is_screenshot_composite', False),
            'screenshot_evidence': html_data.get('screenshot_evidence', ''),
            'strict_fields': html_data.get('strict_fields', []),
            'ambiguous_fields': html_data.get('ambiguous_fields', []),
            'filter_area': html_data.get('filter_area', {
                'has_filter': False,
                'filter_fields': [],
                'filter_actions': [],
            }),
        }
        page_info['page_category'] = classify_page(page_info)
        result['pages'].append(page_info)

    result['total_pages'] = len(result['pages'])
    return result


def parse_mastergo_directory(directory_path):
    """
    解析 MasterGo 离线标注导出。
    
    MasterGo 离线标注插件导出结构：
    - index.html: 入口
    - 含 PAGED_FRAMES / SETTINGS / FILE_DATA 的 .js 文件（数据文件）
    
    策略：定位数据 JS 文件，解析 PAGED_FRAMES 中的画板信息；
    若无法解析，退化为通用 HTML 扫描。
    """
    directory_path = os.path.abspath(directory_path)
    
    result = {
        'type': 'mastergo_directory',
        'tool': 'mastergo',
        'root_path': directory_path,
        'project_name': os.path.basename(directory_path),
        'pages': [],
        'page_tree': [],
        'total_pages': 0,
    }
    
    # 查找含 PAGED_FRAMES 的 JS 文件
    data_js_path = None
    for root, dirs, files in os.walk(directory_path):
        depth = root[len(directory_path):].count(os.sep)
        if depth > 2:
            continue
        for f in files:
            if not f.endswith('.js'):
                continue
            try:
                with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as fh:
                    chunk = fh.read(5000)
                if 'PAGED_FRAMES' in chunk:
                    data_js_path = os.path.join(root, f)
                    break
            except (FileNotFoundError, IOError):
                pass
        if data_js_path:
            break
    
    # 若找到数据文件，尝试解析画板信息
    if data_js_path:
        try:
            with open(data_js_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            import re
            # 提取画板名称（name 字段）
            names = re.findall(r'"name":\s*"([^"]+)"', content)
            # 提取画板 ID
            ids = re.findall(r'"id":\s*"([^"]+)"', content)
            
            for name, fid in zip(names, ids):
                result['pages'].append({
                    'pageName': name,
                    'url': '',
                    'texts': [],
                    'widgets': [],
                    'has_html': False,
                    'has_data_js': True,
                })
            result['total_pages'] = len(result['pages'])
            return result
        except (FileNotFoundError, IOError):
            pass
    
    # 退化为通用 HTML 扫描
    return parse_loose_html_files_with_tool(directory_path, 'mastergo')


def parse_lanhu_directory(directory_path):
    """
    解析蓝湖导出。
    
    蓝湖导出可能形式：
    - 设计稿代码导出：HTML + CSS（单个页面或组件代码）
    - Schema JSON：结构化图层树
    
    策略：优先查找 .schema.json 文件，提取图层结构；
    若无，退化为通用 HTML 扫描。
    """
    directory_path = os.path.abspath(directory_path)
    
    result = {
        'type': 'lanhu_directory',
        'tool': 'lanhu',
        'root_path': directory_path,
        'project_name': os.path.basename(directory_path),
        'pages': [],
        'page_tree': [],
        'total_pages': 0,
    }
    
    # 查找 .schema.json 文件
    schema_files = []
    for root, dirs, files in os.walk(directory_path):
        depth = root[len(directory_path):].count(os.sep)
        if depth > 2:
            continue
        for f in files:
            if f.endswith('.schema.json'):
                schema_files.append(os.path.join(root, f))
        dirs[:] = [d for d in dirs if d not in ('node_modules', '.git')]
    
    # 解析 schema JSON
    for schema_path in schema_files:
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            # 蓝湖 schema 含图层树，提取页面名称和文本
            page_name = os.path.basename(schema_path).replace('.schema.json', '')
            texts = []
            widgets = []
            
            # 递归遍历图层树提取文本
            def traverse(node):
                if isinstance(node, dict):
                    if node.get('type') == 'lanhutext' and node.get('text'):
                        texts.append(node['text'])
                    if node.get('type'):
                        widgets.append({
                            'id': node.get('id', ''),
                            'label': node.get('text', ''),
                            'friendlyType': node.get('type', ''),
                            'type_en': node.get('type', ''),
                        })
                    for v in node.values():
                        traverse(v)
                elif isinstance(node, list):
                    for item in node:
                        traverse(item)
            
            traverse(schema)
            
            result['pages'].append({
                'pageName': page_name,
                'url': os.path.basename(schema_path),
                'texts': texts,
                'widgets': widgets,
                'notes': [],
                'has_html': False,
                'has_data_js': True,
            })
        except (json.JSONDecodeError, FileNotFoundError, IOError):
            continue
    
    if result['pages']:
        result['total_pages'] = len(result['pages'])
        return result
    
    # 退化为通用 HTML 扫描
    return parse_loose_html_files_with_tool(directory_path, 'lanhu')


def parse_loose_html_files_with_tool(directory_path, tool_type):
    """解析目录中的多个 HTML 文件，标注工具类型。"""
    result = parse_loose_html_files(directory_path)
    result['type'] = f'{tool_type}_loose_directory'
    result['tool'] = tool_type
    return result


def parse_axure_directory(directory_path):
    """
    解析完整的原型导出目录。
    
    自动识别工具类型（Axure/墨刀/MasterGo/蓝湖），分发到对应解析器。
    若无法识别，退化为通用 HTML 解析。
    
    返回结构化的原型数据。
    """
    directory_path = os.path.abspath(directory_path)
    
    # 检查是否为单个 HTML 文件
    if os.path.isfile(directory_path):
        return parse_single_html_file(directory_path)
    
    # 识别工具类型
    tool_type = detect_tool_type(directory_path)
    
    # 分发到对应解析器
    if tool_type == 'axure':
        return _parse_axure_full(directory_path)
    elif tool_type == 'mockplus':
        return parse_mockplus_directory(directory_path)
    elif tool_type == 'mastergo':
        return parse_mastergo_directory(directory_path)
    elif tool_type == 'lanhu':
        return parse_lanhu_directory(directory_path)
    else:
        # 未知工具，退化为通用 HTML 扫描
        return parse_loose_html_files_with_tool(directory_path, 'unknown')


def _parse_axure_full(directory_path):
    """解析完整的 Axure 导出目录（内部函数）。"""
    document_js = os.path.join(directory_path, 'data', 'document.js')
    
    result = {
        'type': 'axure_directory',
        'tool': 'axure',
        'root_path': directory_path,
        'project_name': os.path.basename(directory_path),
        'pages': [],
        'page_tree': [],
        'total_pages': 0,
    }
    
    # 1. 解析页面树
    page_tree = build_page_tree(document_js)
    result['page_tree'] = page_tree
    
    # 2. 获取扁平页面列表
    flat_pages = extract_pages_flat(document_js)
    result['total_pages'] = len(flat_pages)
    
    # 3. 解析每个页面的 HTML 和 data.js
    for page in flat_pages:
        page_name = page['pageName']
        page_url = page['url']
        
        html_path = os.path.join(directory_path, page_url)
        data_js_path = os.path.join(directory_path, 'files', page_name, 'data.js')
        
        page_info = {
            'pageName': page_name,
            'url': page_url,
            'texts': [],
            'widgets': [],
            'notes': [],
            'interactions': [],
            'has_html': os.path.exists(html_path),
            'has_data_js': os.path.exists(data_js_path),
            'is_screenshot_composite': False,
            'screenshot_evidence': '',
            'strict_fields': [],
            'ambiguous_fields': [],
            'filter_area': {
                'has_filter': False,
                'filter_fields': [],
                'filter_actions': [],
            },
            'table_columns': [],
        }

        # 解析 HTML
        if os.path.exists(html_path):
            html_data = parse_page_html(html_path)
            page_info['texts'] = html_data['texts']
            page_info['html_widgets'] = html_data['widgets']
            page_info['notes'] = html_data.get('notes', [])
            page_info['is_screenshot_composite'] = html_data.get('is_screenshot_composite', False)
            page_info['screenshot_evidence'] = html_data.get('screenshot_evidence', '')
            page_info['strict_fields'] = html_data.get('strict_fields', [])
            page_info['ambiguous_fields'] = html_data.get('ambiguous_fields', [])
            page_info['filter_area'] = html_data.get('filter_area', page_info['filter_area'])
            page_info['table_columns'] = html_data.get('table_columns', [])

        # 解析 data.js
        if os.path.exists(data_js_path):
            js_data = parse_page_data_js(data_js_path)
            page_info['widgets'] = js_data['widgets']
            page_info['interactions'] = js_data['interactions']

        page_info['page_category'] = classify_page(page_info)
        result['pages'].append(page_info)

    # ===== 磁盘 fallback：发现磁盘上有但 document.js 中未注册的 HTML 文件 =====
    disk_html_files = set(os.path.basename(f) for f in _glob.glob(os.path.join(directory_path, '*.html')))
    doc_html_files = set(p['url'] for p in flat_pages)
    # 排除 Axure 框架文件
    framework_exclude = {'index.html', 'start.html', 'start_c_1.html', 'start_with_pages.html'}
    missing_files = disk_html_files - doc_html_files - framework_exclude

    for html_file in sorted(missing_files):
        html_path = os.path.join(directory_path, html_file)
        html_data = parse_page_html(html_path)
        # 推断 pageName：优先用 <title> 标签内容，否则用文件名
        page_name = html_data.get('title', '') or html_file.replace('.html', '')
        page_info = {
            'pageName': page_name,
            'url': html_file,
            'texts': html_data['texts'],
            'widgets': [],
            'notes': html_data.get('notes', []),
            'interactions': [],
            'has_html': True,
            'has_data_js': False,  # 磁盘文件通常无 data.js
            'is_screenshot_composite': html_data.get('is_screenshot_composite', False),
            'screenshot_evidence': html_data.get('screenshot_evidence', ''),
            'strict_fields': html_data.get('strict_fields', []),
            'ambiguous_fields': html_data.get('ambiguous_fields', []),
            'filter_area': html_data.get('filter_area', {
                'has_filter': False, 'filter_fields': [], 'filter_actions': [],
            }),
            'table_columns': html_data.get('table_columns', []),
        }
        page_info['page_category'] = classify_page(page_info)
        result['pages'].append(page_info)
        print(f"⚠️ 磁盘发现未注册页面，已纳入解析: {html_file}", file=sys.stderr)

    result['total_pages'] = len(result['pages'])

    # 去全局菜单噪声
    menu_noise = build_menu_noise_set(result['pages'])
    for page in result['pages']:
        page['menu_noise_count'] = len(menu_noise)  # 备查
        # 不直接删除 texts，而是新增 cleaned_texts 字段
        page['cleaned_texts'] = [t for t in page.get('texts', []) if t not in menu_noise]

    return result


def parse_loose_html_files(directory_path):
    """解析目录中的多个 HTML 文件（没有 document.js 的情况）。"""
    result = {
        'type': 'loose_directory',
        'root_path': directory_path,
        'project_name': os.path.basename(directory_path),
        'pages': [],
        'total_pages': 0,
    }

    html_files = discover_page_html_files(directory_path)

    for html_file in html_files:
        html_path = os.path.join(directory_path, html_file)
        page_name = html_file.replace('.html', '')

        html_data = parse_page_html(html_path)

        page_info = {
            'pageName': page_name,
            'url': html_file,
            'texts': html_data['texts'],
            'widgets': html_data['widgets'],
            'notes': html_data.get('notes', []),
        }
        result['pages'].append(page_info)

    result['total_pages'] = len(result['pages'])
    return result


def parse_single_html_file(filepath):
    """解析单个 Axure 页面 HTML 文件。"""
    filepath = os.path.abspath(filepath)

    html_data = parse_page_html(filepath)

    # 尝试查找同级的 data 目录
    base_dir = os.path.dirname(filepath)
    parent_dir = os.path.dirname(base_dir)

    document_js = None
    for candidate in [
        os.path.join(base_dir, 'data', 'document.js'),
        os.path.join(parent_dir, 'data', 'document.js'),
    ]:
        if os.path.exists(candidate):
            document_js = candidate
            break

    result = {
        'type': 'single_file',
        'filepath': filepath,
        'project_name': os.path.basename(filepath),
        'title': html_data['title'],
        'texts': html_data['texts'],
        'widgets': html_data['widgets'],
        'notes': html_data.get('notes', []),
        'has_sitemap': document_js is not None,
    }
    
    if document_js:
        pages = extract_pages_flat(document_js)
        result['pages'] = pages
        result['total_pages'] = len(pages)
    
    return result


def format_tree(tree, indent=0, is_last_of_parent=True, prefix=''):
    """递归格式化页面树为可读文本。"""
    lines = []
    for i, node in enumerate(tree):
        is_last = (i == len(tree) - 1)
        connector = '└── ' if is_last else '├── '
        folder_mark = ' 📁' if node.get('isFolder') else ''
        name = f"{node['pageName']}{folder_mark}"
        lines.append(f"{prefix}{connector}{name}")
        
        child_prefix = prefix + ('    ' if is_last else '│   ')
        if node.get('children'):
            lines.extend(format_tree(node['children'], indent + 1, is_last, child_prefix))
    
    return lines


def format_parse_result(result):
    """将解析结果格式化为可读文本，供用户预览。"""
    lines = []
    
    if result['type'] in ('directory', 'axure_directory', 'loose_directory'):
        lines.append(f"📁 项目名称: {result['project_name']}")
        lines.append(f"📄 页面总数: {result['total_pages']}")
        lines.append("")
        lines.append("📑 页面结构:")
        
        # 构建树形展示
        tree = result.get('page_tree', [])
        tree_lines = format_tree(tree)
        for tree_line in tree_lines:
            lines.append(f"  {tree_line}")
        
        lines.append("")
        lines.append("📝 页面内容摘要:")
        for page in result.get('pages', []):
            texts = page.get('texts', [])
            summary = texts[:5] if texts else ["(无文本内容)"]
            lines.append(f"\n  📄 [{page['pageName']}]")
            for t in summary:
                lines.append(f"     - {t}")
            if len(texts) > 5:
                lines.append(f"     ... 共 {len(texts)} 个文本元素")
            
            # 控件摘要
            widgets = page.get('widgets', [])
            if widgets:
                types = {}
                for w in widgets:
                    t = w.get('friendlyType', '未知')
                    types[t] = types.get(t, 0) + 1
                type_str = ", ".join([f"{k}×{v}" for k, v in types.items()])
                lines.append(f"     控件: {type_str}")
            
            # 交互摘要
            interactions = page.get('interactions', [])
            if interactions:
                lines.append(f"     交互事件: {len(interactions)} 个")
    
    elif result['type'] == 'single_file':
        lines.append(f"📄 文件: {result['project_name']}")
        lines.append(f"📝 页面标题: {result['title']}")
        lines.append("")
        lines.append("文本内容:")
        for t in result.get('texts', []):
            lines.append(f"  - {t}")
        if result.get('has_sitemap'):
            lines.append(f"\n(检测到同级的 sitemap，共 {result.get('total_pages', 0)} 个页面)")
    
    return "\n".join(lines)


def generate_json_summary(result):
    """生成 JSON 摘要（用于程序化处理）。"""
    summary = {
        'type': result.get('type', 'unknown'),
        'project_name': result.get('project_name', ''),
        'total_pages': result.get('total_pages', 0),
        'pages': []
    }

    # 所有目录类型（axure/mockplus/mastergo/lanhu/loose/plain）均纳入 page_tree
    result_type = result.get('type', '')
    if result_type in ('axure_directory', 'mockplus_directory', 'mastergo_directory',
                       'lanhu_directory', 'loose_directory', 'directory'):
        summary['page_tree'] = result.get('page_tree', [])
    
    for page in result.get('pages', []):
        page_summary = {
            'pageName': page['pageName'],
            'url': page.get('url', ''),
            'texts': page.get('texts', []),
            'widget_types': {},
            'interaction_count': len(page.get('interactions', [])),
        }
        for w in page.get('widgets', []):
            t = w.get('friendlyType', '未知')
            page_summary['widget_types'][t] = page_summary['widget_types'].get(t, 0) + 1
        
        summary['pages'].append(page_summary)
    
    return summary


def parse_page_selection(spec, pages):
    """
    解析用户输入的页面选择字符串，返回选中的页面索引列表（0-based）。

    支持的语法（逗号分隔，可混合）：
      - `all`：选中全部页面
      - 页面名（精确匹配 pageName 或 url/文件名，含 .html 后缀也可）
      - 数字索引（1-based，即用户看到的序号）
      - 范围 `N-M`（1-based 闭区间）

    注意：同一页面若被多个 token 匹配，索引可以重复出现，
    以支持页面属于多个模块的场景（多对多关系）。

    参数:
        spec: 用户输入字符串，如 "1,3-5,概述"
        pages: 解析结果中的 pages 列表（每个 dict 含 pageName）

    返回:
        (selected_indices, errors)
        selected_indices: 排序后的 0-based 索引列表（可能含重复项）
        errors: 无法识别的 token 列表
    """
    if not spec or not spec.strip():
        return list(range(len(pages))), []

    tokens = [t.strip() for t in spec.split(',') if t.strip()]
    selected = []  # 使用列表而非集合，允许重复
    errors = []
    total = len(pages)

    for tok in tokens:
        if tok.lower() == 'all':
            return list(range(total)), []

        # 范围 N-M
        m = re.match(r'^(\d+)\s*-\s*(\d+)$', tok)
        if m:
            start = int(m.group(1))
            end = int(m.group(2))
            if start < 1 or end < 1 or start > total or end > total:
                errors.append(tok)
                continue
            lo, hi = min(start, end), max(start, end)
            for idx in range(lo - 1, hi):
                selected.append(idx)
            continue

        # 单个数字索引（1-based）
        if re.match(r'^\d+$', tok):
            idx = int(tok) - 1
            if 0 <= idx < total:
                selected.append(idx)
            else:
                errors.append(tok)
            continue

        # 页面名匹配（支持带或不带 .html 后缀，优先匹配 pageName，其次 url/文件名）
        normalized_tok = tok[:-5] if tok.endswith('.html') else tok
        matched = False

        # 第一优先级：pageName 精确匹配
        for i, page in enumerate(pages):
            pname = page.get('pageName', '')
            if pname == tok or pname == normalized_tok:
                selected.append(i)
                matched = True
                break

        # 第二优先级：url/文件名匹配
        if not matched:
            for i, page in enumerate(pages):
                purl = page.get('url', '')
                url_no_ext = purl[:-5] if purl.endswith('.html') else purl
                if purl == tok or url_no_ext == tok or purl == tok + '.html' or url_no_ext == normalized_tok:
                    selected.append(i)
                    matched = True
                    break

        if not matched:
            errors.append(tok)

    return sorted(selected), errors


def filter_result_by_pages(result, selected_indices):
    """
    根据选中的页面索引（0-based）过滤解析结果，保留 page_tree 的完整性
    以便用户参考层级，但 pages 列表只包含选中的页面。
    """
    if not selected_indices:
        return result

    selected_set = set(selected_indices)
    filtered_pages = [page for i, page in enumerate(result.get('pages', [])) if i in selected_set]

    new_result = dict(result)
    new_result['pages'] = filtered_pages
    new_result['total_pages'] = len(filtered_pages)
    new_result['selected_page_count'] = len(filtered_pages)
    new_result['selected_indices'] = list(selected_indices)
    return new_result


def format_page_list(result, group_by=None):
    """格式化页面清单（带序号）供用户选择。
    当 group_by='prefix' 时，按文件名共同前缀分组展示。"""
    lines = []
    lines.append(f"📁 项目: {result.get('project_name', '')}")
    total = result.get('total_pages', 0)
    lines.append(f"📄 识别到的页面总数: {total}")
    lines.append("")

    pages = result.get('pages', [])

    if group_by == 'prefix':
        # 按文件名前缀分组（取第一个 _ 或 - 或 （ 之前的部分）
        groups = defaultdict(list)
        for i, page in enumerate(pages, start=1):
            url = page.get('url', '')
            prefix = re.split(r'[-_（(]', url)[0]
            groups[prefix].append((i, page))

        for prefix, items in sorted(groups.items()):
            lines.append(f"\n📁 {prefix} ({len(items)} 页)")
            for idx, page in items:
                pname = page.get('pageName', '(未命名)')
                url = page.get('url', '')
                text_count = len(page.get('texts', []))
                widget_count = len(page.get('widgets', []))
                interaction_count = len(page.get('interactions', []))
                lines.append(
                    f"    {idx:>4}. {pname}"
                    f"  [文本×{text_count}, 控件×{widget_count}, 交互×{interaction_count}]"
                    f"  {url}"
                )
    else:
        lines.append("可选择的页面清单（序号为选择时使用的编号）：")
        for i, page in enumerate(pages, start=1):
            pname = page.get('pageName', '(未命名)')
            url = page.get('url', '')
            text_count = len(page.get('texts', []))
            widget_count = len(page.get('widgets', []))
            interaction_count = len(page.get('interactions', []))
            lines.append(
                f"  {i:>3}. {pname}"
                f"  [文本×{text_count}, 控件×{widget_count}, 交互×{interaction_count}]"
                f"  {url}"
            )

    lines.append("")
    lines.append("选择语法示例：")
    lines.append("  all                         # 选择全部页面")
    lines.append("  1,3,5                       # 按序号多选")
    lines.append("  2-6                         # 按序号范围（闭区间）")
    lines.append("  1,3-5,概述                  # 混合序号/范围/页面名")
    lines.append("  概述,业务.html              # 按页面名（带不带 .html 均可）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 品牌词汇过滤
# ---------------------------------------------------------------------------

# brand_filter.json 的加载路径（相对于脚本所在目录）
_BRAND_FILTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   '..', 'references', 'brand_filter.json')


def load_brand_filter():
    """加载品牌过滤配置。"""
    try:
        with open(_BRAND_FILTER_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {'enabled': False, 'patterns': [], 'replacement': '(示例)',
                'description': ''}


def apply_brand_filter(text, filters=None):
    """对输出文本中的品牌词汇做替换。"""
    if filters is None:
        filters = load_brand_filter()
    if not filters or not filters.get('enabled'):
        return text
    replacement = filters.get('replacement', '(示例)')
    for pattern in filters.get('patterns', []):
        text = text.replace(pattern, replacement)
    return text


def main():
    """命令行入口：解析原型并输出摘要，支持页面选择过滤。"""
    parser = argparse.ArgumentParser(description='解析 Axure/墨刀/MasterGo/蓝湖原型文件')
    parser.add_argument('path', help='原型目录或HTML文件路径')
    parser.add_argument('--json', action='store_true', help='输出完整 JSON（含所有文本/控件/交互）')
    parser.add_argument('--json-summary', action='store_true', help='输出 JSON 摘要（推荐，便于程序化处理）')
    parser.add_argument('--list-pages', action='store_true', help='仅列出页面清单（带序号），供用户选择')
    parser.add_argument('--list-pages-group', action='store_true', help='按文件名前缀分组的页面清单')
    parser.add_argument('--pages', type=str, help='按选择过滤页面，如 1,3-5,概述')
    args = parser.parse_args()

    path = args.path
    if args.json:
        output_mode = 'json'
    elif args.json_summary:
        output_mode = 'json-summary'
    else:
        output_mode = 'text'
    list_pages = args.list_pages or args.list_pages_group
    pages_spec = args.pages

    if not os.path.exists(path):
        print(f"错误: 路径不存在: {path}")
        sys.exit(1)

    result = parse_axure_directory(path)

    # 页面选择过滤（仅对含 pages 列表的解析结果生效；单文件结果直接跳过）
    if pages_spec is not None:
        all_pages = result.get('pages', [])
        if not all_pages:
            print("提示: 当前解析结果不含页面列表（如单个 HTML 文件），已忽略 --pages 参数。", file=sys.stderr)
        else:
            selected, errors = parse_page_selection(pages_spec, all_pages)
            if errors:
                print(f"警告: 以下选择项无法识别，已忽略：{', '.join(errors)}", file=sys.stderr)
            if not selected:
                print("错误: 没有选中任何页面，请检查 --pages 参数。", file=sys.stderr)
                sys.exit(2)
            result = filter_result_by_pages(result, selected)

    if list_pages:
        group_by = 'prefix' if args.list_pages_group else None
        print(format_page_list(result, group_by=group_by))
        return

    if output_mode == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif output_mode == 'json-summary':
        try:
            print(json.dumps(generate_json_summary(result), ensure_ascii=False, indent=2))
        except Exception as e:
            print(f'{{"error": "generate_json_summary failed: {e}"}}', file=sys.stderr)
            print(json.dumps(result, ensure_ascii=False, indent=2))  # fallback to full json
    else:
        print(format_parse_result(result))


if __name__ == '__main__':
    main()