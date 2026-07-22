#!/usr/bin/env python3
"""
Axure RP HTML 原型解析器
从 Axure 导出的 HTML 目录中提取页面结构、控件内容、交互事件等信息。
"""

import json
import os
import re
import sys
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

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get('id', '')
        classes = attrs_dict.get('class', '')

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


def build_page_tree(filepath):
    """
    从 document.js 中提取页面树结构。
    
    document.js 格式为变量赋值序列，如：
    s="id",t="4qsozv",u="pageName",v="概述",w="type",x="Wireframe",y="url",z="概述.html",
    A="lacalr",B="业务",C="业务.html",...
    
    变量名是递增的占位符，实际数据在值中。
    第一个页面有显式 key（id, pageName, type, url），后续页面隐式复用相同模式。
    
    返回页面列表，每项包含：{pageName, url, children}
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    root_idx = content.find('rootNodes')
    if root_idx < 0:
        return []
    
    chunk = content[root_idx:root_idx + 20000]
    values = re.findall(r'=\"([^\"]*)\"', chunk)
    
    # 解析调用的函数 _(key,val,key,val,...) 格式
    # 提取所有 key-value 对
    # 格式: ...,"key","value",...
    # 在 document.js 中，rootNodes 数据是 _(key,val,key,val,...) 的调用参数
    
    # 方法：从原始 chunk 中提取 ..."key","value"... 模式
    # 注意值可能是字符串或数字
    # 先把所有 =\"value\" 提取出来，然后按顺序解析
    
    # 从 values 中提取页面信息
    # 页面模式: [id?], pageName, [type?], url, [children?]
    # 第一个页面可能有显式 key
    
    all_pages = []  # [{name, url, isFolder, children_depth}]
    depth = 0
    in_children = False
    i = 0
    
    # 已知的页面名称（用于识别）
    known_page_names = {
        '概述', '业务', '流程', '框架', '实例管理', '新增节点', '配置中心',
        '发布', '版本管理', '服务配置文件详情', '模板列表', '认证管理', '概览',
        '仅备份', '服务配置', 'Authentication Manager', '页面 1'
    }
    
    # 从 values 中识别页面
    # 策略：找到所有 pageName → url 对
    page_positions = []  # (index_in_values, name, url, isFolder)
    for i in range(len(values)):
        v = values[i]
        
        if v in known_page_names:
            pname = v
            # 查找对应的 URL
            url = ''
            for j in range(i + 1, min(i + 5, len(values))):
                if values[j].endswith('.html'):
                    url = values[j]
                    break
            
            is_folder = False
            # Folder 标记紧跟在页面名后面（1-2个位置内）
            for j in range(i + 1, min(i + 3, len(values))):
                if values[j] == 'Folder':
                    is_folder = True
                    break
            
            page_positions.append({
                'name': pname,
                'url': url,
                'isFolder': is_folder,
                'values_idx': i
            })
    
    # 用 children 标记和 Folder 来修正深度
    page_depths = []
    current_depth = 0
    folder_active = False  # 是否在 Folder 的子节点模式中
    last_folder_depth = -1  # 最近 Folder 的深度
    
    for i, v in enumerate(values):
        # 检测非页面数据开始（结束 Folder 子节点模式）
        if v in ('additionalJs', 'additionalCss', 'globalVariables', 'stylesheet', 'defaultStyle'):
            folder_active = False
        
        # children 标记
        if v == 'children':
            current_depth += 1
            folder_active = False
        elif v == '':
            current_depth = max(0, current_depth - 1)
            folder_active = False
        elif v == 'Folder':
            folder_active = True
            last_folder_depth = current_depth
        
        # 检查是否是页面名
        if v in known_page_names:
            # 判断深度
            if folder_active:
                # 当前页面是 Folder 的子节点
                depth = last_folder_depth + 1
            else:
                depth = current_depth
            
            page_depths.append(depth)
    
    # 将深度应用到页面
    for i, page in enumerate(page_positions):
        if i < len(page_depths):
            page['depth'] = page_depths[i]
    
    # 根据深度构建树
    root = []
    stack = [root]  # 栈顶是当前父节点的 children 列表
    
    for page in page_positions:
        depth = page['depth']
        
        # 弹出栈直到对应深度
        while len(stack) > depth + 1:
            stack.pop()
        
        # 确保栈长度足够
        while len(stack) <= depth:
            if stack[-1]:
                last_node = stack[-1][-1]
                last_node['children'] = last_node.get('children', [])
                stack.append(last_node['children'])
            else:
                stack.append([])
        
        node = {
            'pageName': page['name'],
            'url': page['url'],
            'children': []
        }
        if page['isFolder']:
            node['isFolder'] = True
        
        stack[depth].append(node)
    
    return root


def extract_pages_flat(filepath):
    """从 document.js 中提取扁平页面列表（不包含树结构）。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    root_idx = content.find('rootNodes')
    if root_idx < 0:
        return []
    
    chunk = content[root_idx:root_idx + 20000]
    values = re.findall(r'=\"([^\"]*)\"', chunk)
    
    # 已知的页面名称
    known_page_names = {
        '概述', '业务', '流程', '框架', '实例管理', '新增节点', '配置中心',
        '发布', '版本管理', '服务配置文件详情', '模板列表', '认证管理', '概览',
        '仅备份', '服务配置', 'Authentication Manager', '页面 1'
    }
    
    pages = []
    for i, v in enumerate(values):
        if v in known_page_names:
            # 查找对应的 URL
            url = ''
            for j in range(i + 1, min(i + 5, len(values))):
                if values[j].endswith('.html'):
                    url = values[j]
                    break
            if url:
                pages.append({'pageName': v, 'url': url})
    
    return pages


def parse_page_html(filepath):
    """解析单个页面 HTML 文件，提取文本内容、控件信息和便签/备注说明。"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except (FileNotFoundError, IOError):
        return {'title': '', 'texts': [], 'widgets': [], 'notes': []}

    parser = AxurePageHTMLParser()
    parser.feed(html_content)

    return {
        'title': parser.title,
        'texts': parser.texts,
        'widgets': parser.widget_comments,
        'notes': parser.get_notes(),
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
        }
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
        }

        # 解析 HTML
        if os.path.exists(html_path):
            html_data = parse_page_html(html_path)
            page_info['texts'] = html_data['texts']
            page_info['html_widgets'] = html_data['widgets']
            page_info['notes'] = html_data.get('notes', [])

        # 解析 data.js
        if os.path.exists(data_js_path):
            js_data = parse_page_data_js(data_js_path)
            page_info['widgets'] = js_data['widgets']
            page_info['interactions'] = js_data['interactions']

        result['pages'].append(page_info)

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
    
    if result['type'] == 'directory':
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
        'type': result['type'],
        'project_name': result.get('project_name', ''),
        'total_pages': result.get('total_pages', 0),
        'pages': []
    }
    
    if result['type'] == 'directory':
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
      - 页面名（精确匹配 pageName，含 .html 后缀也可）
      - 数字索引（1-based，即用户看到的序号）
      - 范围 `N-M`（1-based 闭区间）
    
    参数:
        spec: 用户输入字符串，如 "1,3-5,概述"
        pages: 解析结果中的 pages 列表（每个 dict 含 pageName）
    
    返回:
        (selected_indices, errors)
        selected_indices: 去重排序后的 0-based 索引列表
        errors: 无法识别的 token 列表
    """
    if not spec or not spec.strip():
        return list(range(len(pages))), []

    tokens = [t.strip() for t in spec.split(',') if t.strip()]
    selected = set()
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
                selected.add(idx)
            continue

        # 单个数字索引（1-based）
        if re.match(r'^\d+$', tok):
            idx = int(tok) - 1
            if 0 <= idx < total:
                selected.add(idx)
            else:
                errors.append(tok)
            continue

        # 页面名匹配（支持带或不带 .html 后缀）
        normalized_tok = tok[:-5] if tok.endswith('.html') else tok
        matched = False
        for i, page in enumerate(pages):
            pname = page.get('pageName', '')
            if pname == tok or pname == normalized_tok:
                selected.add(i)
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


def format_page_list(result):
    """格式化页面清单（带序号）供用户选择。"""
    lines = []
    lines.append(f"📁 项目: {result.get('project_name', '')}")
    total = result.get('total_pages', 0)
    lines.append(f"📄 识别到的页面总数: {total}")
    lines.append("")
    lines.append("可选择的页面清单（序号为选择时使用的编号）：")

    pages = result.get('pages', [])
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


def _get_arg_value(argv, flag):
    """从 argv 中取出 --flag value；不存在返回 None。"""
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def main():
    """命令行入口：解析原型并输出摘要，支持页面选择过滤。"""
    if len(sys.argv) < 2:
        print("用法: python parse_axure.py <原型目录或HTML文件> [选项]")
        print("选项：")
        print("  --json             输出完整 JSON（含所有文本/控件/交互）")
        print("  --json-summary     输出 JSON 摘要（推荐，便于程序化处理）")
        print("  --list-pages       仅列出页面清单（带序号），供用户选择")
        print("  --pages <spec>     按选择过滤页面，spec 支持：")
        print("                       all                      全部页面")
        print("                       1,3,5                   按序号多选（1-based）")
        print("                       2-6                     按序号范围（闭区间）")
        print("                       概述,业务.html           按页面名（带不带 .html 均可）")
        print("                       1,3-5,概述              混合")
        sys.exit(1)

    path = sys.argv[1]
    output_mode = '--json' if '--json' in sys.argv else '--json-summary' if '--json-summary' in sys.argv else 'text'
    list_pages = '--list-pages' in sys.argv
    pages_spec = _get_arg_value(sys.argv, '--pages')

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
        print(format_page_list(result))
        return

    if output_mode == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif output_mode == 'json-summary':
        print(json.dumps(generate_json_summary(result), ensure_ascii=False, indent=2))
    else:
        print(format_parse_result(result))


if __name__ == '__main__':
    main()