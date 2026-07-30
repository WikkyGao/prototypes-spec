# prototypes-spec Skill 优化方案 v2.0

> 基于 2026-07-30 会话深入诊断，面向 skill 开发者。
> 目标目录：`~/.claude/skills/prototypes-spec/`

---

## 一、优化概览

| 优先级 | 数量 | 类别 |
|--------|------|------|
| 🔴 P0（必须修复） | 4 | 阻塞性 bug — 不修则无法正常工作 |
| 🟡 P1（应该修复） | 4 | 准确性缺陷 — 产出的 PRD 字段/列会大量遗漏 |
| 🟢 P2（建议优化） | 3 | 效率/噪音 — 增加手动修正工作量 |
| **总计** | **11** | |

---

## 二、P0 级别（阻塞性 Bug）

### P0-1: `--json` 输出不纯、无法被 pipeline 消费

**文件**：`scripts/parse_axure.py`，line 1619~1653（`main()` 函数）

**现象**：运行 `python3 parse_axure.py <dir> --json > out.json` 后，`out.json` 内容不是 JSON，而是 "📁 项目名称: xxx" 人类可读文本。

**根因**：line 1620 的 `output_mode` 用 `'--json' in sys.argv` 做字符串检测，当 `sys.argv` 是 `['parse_axure.py', '<dir>', '--pages', '348', '--json']` 时理应命中，但整个会话中反复验证发现 `--json` 确实在 argv 里、代码逻辑也走到了 line 1648，**输出却是 `format_parse_result()` 的内容**。最终定位：line 1653 的 `else` 分支在某些场景下被触发——最可能的原因是 `generate_json_summary()` 在 line 1449 抛出 KeyError（见 P0-3），异常被静默吞掉后走了 text 输出。

**修改**（2 处）：

a) line 1620，将手工 argv 扫描替换为 argparse：

```python
import argparse

def main():
    parser = argparse.ArgumentParser(description='解析 Axure/墨刀/MasterGo/蓝湖原型文件')
    parser.add_argument('path', help='原型目录或HTML文件路径')
    parser.add_argument('--json', action='store_true', help='输出完整 JSON')
    parser.add_argument('--json-summary', action='store_true', help='输出 JSON 摘要')
    parser.add_argument('--list-pages', action='store_true', help='列出页面清单')
    parser.add_argument('--pages', type=str, help='按选择过滤页面，如 1,3-5,概述')
    args = parser.parse_args()

    path = args.path
    output_mode = 'json' if args.json else ('json-summary' if args.json_summary else 'text')
    list_pages = args.list_pages
    pages_spec = args.pages
    # ... 后续逻辑不变
```

b) line 1648~1653，增加异常保护：

```python
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
```

---

### P0-2: `--pages` 只能按 Axure 内部 `pageName` 匹配，不能按文件名（url）匹配

**文件**：`scripts/parse_axure.py`，line 1475~1540（`parse_page_selection()` 函数）

**现象**：用户想选 `威胁数据看板.html`，必须知道其 Axure 内部名 `pvnzq2`。本会话中所有页面选择 100% 绕过了 `--pages`，改用 Python import + `url_map` 手工过滤。

**根因**：line 1531~1533 只比对 `pageName` 字段：

```python
for i, page in enumerate(pages):
    pname = page.get('pageName', '')
    if pname == tok or pname == normalized_tok:
```

**修改**：增加 `url` 字段匹配，优先级 `pageName` > `url`：

```python
# 替换 line 1528~1538:
# 页面名匹配（支持带或不带 .html 后缀，优先匹配 pageName，其次 url/文件名）
normalized_tok = tok[:-5] if tok.endswith('.html') else tok
matched = False

# 第一优先级：pageName 精确匹配
for i, page in enumerate(pages):
    pname = page.get('pageName', '')
    if pname == tok or pname == normalized_tok:
        selected.add(i)
        matched = True
        break

# 第二优先级：url/文件名匹配
if not matched:
    for i, page in enumerate(pages):
        purl = page.get('url', '')
        url_no_ext = purl[:-5] if purl.endswith('.html') else purl
        if purl == tok or url_no_ext == tok or purl == tok + '.html' or url_no_ext == normalized_tok:
            selected.add(i)
            matched = True
            break

if not matched:
    errors.append(tok)
```

---

### P0-3: `generate_json_summary()` KeyError + 类型比较恒为 False

**文件**：`scripts/parse_axure.py`，line 1446~1472

**现象**：line 1449 `result['type']` 直接索引导致 KeyError；line 1455 `result['type'] == 'directory'` 永远不会为 True（Axure 目录的 type 是 `'axure_directory'`）。

**修改**：

```python
def generate_json_summary(result):
    """生成 JSON 摘要（用于程序化处理）。"""
    summary = {
        'type': result.get('type', 'unknown'),                     # ← 修复 KeyError
        'project_name': result.get('project_name', ''),
        'total_pages': result.get('total_pages', 0),
        'pages': []
    }

    # 修复类型比较：directory / axure_directory / loose_directory 均纳入
    result_type = result.get('type', '')
    if result_type in ('axure_directory', 'mockplus_directory', 'mastergo_directory',
                        'lanhu_directory', 'loose_directory', 'directory'):
        summary['page_tree'] = result.get('page_tree', [])

    # ... 后续不变
```

---

### P0-4: 新增 HTML 文件完全不被识别（磁盘 fallback 缺失）

**文件**：`scripts/parse_axure.py`，line 1231~1298（`_parse_axure_full` 函数）

**现象**：安全有效性验证的 17 个页面（`用例库.html`、`健康度验证.html` 等）存在于磁盘上，但不在 `document.js` 的页面树中。解析器只扫描 `document.js`，**完全忽略这些文件**。本会话直到用户反复提示才通过目录 `ls` 发现。

**根因**：`extract_pages_flat(document_js)`（line 1250）只从 `document.js` 提取页面列表，未与磁盘 `*.html` 做 diff。

**修改**：在 `_parse_axure_full` 的 line 1252 之后，增加磁盘 fallback：

```python
# 3. 解析每个页面的 HTML 和 data.js
for page in flat_pages:
    # ... 现有代码不变 ...

# ===== 新增：磁盘 fallback =====
# 发现磁盘上有但 document.js 中未注册的 HTML 文件
import glob as _glob
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
        'filter_area': html_data.get('filter_area', {'has_filter': False, 'filter_fields': [], 'filter_actions': []}),
    }
    # 添加 page_category
    page_info['page_category'] = classify_page(page_info)
    result['pages'].append(page_info)
    print(f"⚠️ 磁盘发现未注册页面，已纳入解析: {html_file}", file=sys.stderr)

result['total_pages'] = len(result['pages'])
```

---

## 三、P1 级别（准确性缺陷）

### P1-1: Axure 中继器表格列头提取不完整（跨 y 坐标遗漏）

**文件**：`scripts/parse_axure.py`，无现有函数（需新增）

**问题**：Axure 表格用绝对定位 `<div data-left="X" data-top="Y">` 渲染，表头文本分散在多个 y 坐标。人工研判事件 `y=16` 有 16 列头、`y=17` 还有 2 列（"事件进展""攻击IP"）。脚本当前无列头提取逻辑，PRD 中的列字段全靠模型手工数 HTML。

**修改**：在 `parse_page_html` 返回的 dict 中新增 `table_columns` 字段，或在页面的 filter_area/strict_fields 同级新增：

```python
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
    
    from collections import defaultdict
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
```

然后在 `parse_page_html` 中调用：

```python
# 在 parse_page_html 末尾（line 783 之前）加入:
table_columns = extract_table_columns_from_html(html_content)

# 在返回 dict 中加入:
result['table_columns'] = table_columns  # [(列名, x), ...]
```

---

### P1-2: 菜单壳文本污染全部页面 texts

**问题**：Axure 导出后每个页面 HTML 的开头 ~135 条 `<span>` 是全局菜单文本（完全相同），导致 `page['texts']` 被大量噪声污染。后续字段提取、页面分类、列头识别全部受影响。

**修改**：利用 Axure 导出特性——第一个完整页面（或 `功能菜单.html`）的菜单文本是全集。在 `_parse_axure_full` 末尾增加全局去噪：

```python
def build_menu_noise_set(pages):
    """
    从页面 texts 中提取全局菜单噪声集。
    策略：找出现次数最多的前 150 条文本，对大多数页面 (>80%) 都出现的文本即为菜单噪声。
    """
    from collections import Counter
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
    threshold = int(total * 0.8)
    noise = {t for t, c in text_counter.items() if c >= threshold and len(t) >= 1}
    return noise
```

在 `_parse_axure_full` 末尾调用：

```python
# 去全局菜单噪声
menu_noise = build_menu_noise_set(result['pages'])
for page in result['pages']:
    page['menu_noise'] = menu_noise  # 备查
    # 不直接删除 texts，而是新增 cleaned_texts 字段
    page['cleaned_texts'] = [t for t in page.get('texts', []) if t not in menu_noise]
```

---

### P1-3: 字段标签 vs 数据值无法区分，导致示例数据混入字段表

**问题**：资产中心旧版 PRD 中，"王天霸""湖南分公司""集团总部88号"等示例数据被当成字段名列在字段表中。

**修改**：在 `parse_page_html` 中的字段提取逻辑（`strict_fields` 和 `ambiguous_fields`）增加过滤：

```python
def _is_data_value(text, page_texts):
    """
    判断一个文本片段是数据值而非字段标签。
    特征：含数字/IP/人名特征、在页面重复出现、无冒号结尾。
    """
    import re
    # 以 ： 或 : 结尾 → 字段标签
    if text.endswith('：') or text.endswith(':'):
        return False
    # 含 IP 地址
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', text):
        return True
    # 纯数字（含端口、数量、百分比）
    if re.match(r'^[\d.]+[%％]?$', text.strip()):
        return True
    # 含 UUID 或哈希
    if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-', text):
        return True
    # 中文人名特征：2-3个中文字 + 在页面重复 ≥2 次
    if re.match(r'^[一-龥]{2,3}$', text):
        count = page_texts.count(text)
        if count >= 2:
            return True
    return False
```

在 `parse_page_html` 中字段提取循环内调用此函数，数据值跳过不纳入字段表。

---

### P1-4: 同一页面属于多个模块时去重问题

**问题**：`自定义列.html` 同时属于"自动推送事件"和"设备清单"；`更改优先级.html` 同时属于"高危端口"和"事件处置"。页面→模块是多对多关系，但页面列表是扁平结构，选择时可能被去重。

**修改**：在 `parse_page_selection` 和 `filter_result_by_pages` 中不做去重，保持多选语义：

```python
# parse_page_selection: 如果同一页面被多个 token 匹配，索引可以重复出现
# filter_result_by_pages: 保留 selected_indices 中的重复项
# 在生成 PRD 时由上层逻辑决定是否合并
```

更简单的方式：在 `format_page_list` 输出中标注"此页面可能属于多个模块"，让用户在 steps 3~4 中自行判断。

---

## 四、P2 级别（效率/体验优化）

### P2-1: 品牌字眼自动检测与过滤

**文件**：新增配置 `references/brand_filter.json`

**修改**：在解析完成后、生成交付物前，对所有 `texts` 做品牌词汇匹配检查。

```json
// references/brand_filter.json
{
  "enabled": true,
  "patterns": ["PICC", "中国人民保险", "中国人保", "人保集团", "人保财险", "人保寿险", "人保养老"],
  "replacement": "(示例)",
  "description": "品牌词汇替换表，交付物中不得出现这些字眼"
}
```

在生成函数（PRD/功能清单/测试用例等）中增加统一过滤：

```python
def apply_brand_filter(text, filters=None):
    """对输出文本中的品牌词汇做替换。"""
    if not filters or not filters.get('enabled'):
        return text
    for pattern in filters['patterns']:
        text = text.replace(pattern, filters.get('replacement', '(示例)'))
    return text
```

### P2-2: `format_page_list` 增加分组展示

**文件**：`scripts/parse_axure.py`，line 1562 `format_page_list()`

**问题**：579 页的扁平列表无法让用户快速判断哪些页面属于同一模块。

**修改**：在 `format_page_list` 中增加 `--group` 参数，按文件名前缀/关键词自动聚类：

```python
def format_page_list(result, group_by=None):
    """当 group_by='prefix' 时，按文件名共同前缀分组展示。"""
    if group_by != 'prefix':
        # 现有逻辑不变
        ...
    
    # 按文件名前缀分组（取第一个 _ 或 - 之前的部分）
    groups = defaultdict(list)
    for i, page in enumerate(result.get('pages', []), start=1):
        url = page.get('url', '')
        prefix = re.split(r'[-_（]', url)[0]
        groups[prefix].append((i, page))
    
    for prefix, items in sorted(groups.items()):
        print(f"\n📁 {prefix} ({len(items)} 页)")
        for idx, page in items:
            print(f"    {idx:4d}. {page['pageName']:30s} {page['url']}")
```

### P2-3: 生成类脚本增加品牌过滤

**文件**：`scripts/generate_feature_list.py`、`scripts/generate_test_cases.py`、`scripts/generate_data_dict.py`、`scripts/generate_user_stories.py`、`scripts/generate_dev_plan.py`、`scripts/generate_page_flow.py`

**修改**：所有生成脚本在写入文件前调用 `apply_brand_filter()` 对内容做品牌词汇替换。在 `parse_axure.py` 中集中实现该函数，各生成脚本直接 import：

```python
from parse_axure import apply_brand_filter
```

---

## 五、按优先级排序的实施计划

| 阶段 | 条目 | 预计改动量 | 依赖 |
|------|------|-----------|------|
| Sprint 1 | P0-1 argparse 重构 | ~30 行 | 无 |
| Sprint 1 | P0-2 url 匹配 | ~15 行 | 无 |
| Sprint 1 | P0-3 KeyError 修复 | ~5 行 | 无 |
| Sprint 1 | P0-4 磁盘 fallback | ~35 行 | 无 |
| Sprint 2 | P1-1 表头列提取 | ~50 行（新增函数） | P0-4 |
| Sprint 2 | P1-2 菜单噪声过滤 | ~30 行（新增函数） | 无 |
| Sprint 2 | P1-3 字段vs数据区分 | ~25 行 | P1-2 |
| Sprint 3 | P2-1 品牌过滤 | ~20 行 + 新增配置文件 | 无 |
| Sprint 3 | P2-3 生成脚本联动 | ~10 行/脚本 × 6 | P2-1 |
| Sprint 3 | P1-4 多模块去重 | ~10 行 | P0-2 |
| Sprint 3 | P2-2 分组展示 | ~25 行 | 无 |
| **总计** | | **~300 行** | |

---

## 六、不需要修改的项

以下问题不是脚本层面的缺陷，而是**使用流程/模型行为**的问题，不应在脚本中处理：

1. **PRD 功能编号连续性** — 用户按自己定义的模块结构预留编号，脚本不应强制编号连续
2. **PRD 内容是否符合用户期望的页面结构** — 这是模型在生成 PRD 时需要与用户确认的交互环节，不是解析脚本的职责
3. **列表列的顺序和含义** — 列顺序已通过 x 坐标提取，含义描述由模型补充，不需要脚本自动生成
