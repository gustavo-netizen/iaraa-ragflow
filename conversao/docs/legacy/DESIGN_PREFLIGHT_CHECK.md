# Pre-flight Check 模块设计

> 状态: 📝 已设计，待实现
>
> 优先级: P0 (高)
>
> 预计代码量: ~300行

---

## 核心目标

在处理前**提前发现问题**，避免：
- 浪费 API 额度在无法处理的 PDF 上
- 处理到一半才发现文件有问题
- 用户不知道要花多少钱/时间

---

## 检查项目概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Pre-flight Check                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. PDF 完整性检查                                          │
│     ├── 文件是否损坏 (能否正常打开)                         │
│     ├── 是否加密/有密码                                     │
│     └── PDF 版本兼容性                                      │
│                                                             │
│  2. PDF 类型检测                                            │
│     ├── 文本型 PDF (有文字层，可直接提取)                   │
│     ├── 扫描型 PDF (纯图片，需要 OCR)                       │
│     └── 混合型 PDF (部分页有文字，部分是扫描)               │
│                                                             │
│  3. 质量评估                                                │
│     ├── 图像分辨率/DPI 检测                                 │
│     ├── 页面是否空白                                        │
│     └── 是否有水印/背景干扰                                 │
│                                                             │
│  4. 语言检测                                                │
│     ├── 中文 / 英文 / 混合                                  │
│     └── 用于选择合适的 OCR 模型                             │
│                                                             │
│  5. 成本预估                                                │
│     ├── 总页数统计                                          │
│     ├── 预估 Token 消耗                                     │
│     ├── 预估费用 (¥)                                        │
│     └── 预估处理时间                                        │
│                                                             │
│  6. 用户确认                                                │
│     └── 显示摘要，等待用户确认后再开始                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 详细检查逻辑

### 1. PDF 完整性检查

```python
def check_pdf_integrity(pdf_path):
    """
    检查 PDF 文件完整性

    返回:
    {
        'valid': True/False,
        'error': None 或 错误信息,
        'encrypted': True/False,
        'password_protected': True/False,
        'pdf_version': '1.7',
        'file_size_mb': 45.2,
        'page_count': 412
    }
    """
    # 使用 PyPDF2 或 pypdf 尝试打开
    try:
        reader = PdfReader(pdf_path)

        # 检查加密
        if reader.is_encrypted:
            return {'valid': False, 'error': 'PDF 已加密，需要密码'}

        # 获取基本信息
        return {
            'valid': True,
            'page_count': len(reader.pages),
            'pdf_version': reader.pdf_header,
            ...
        }
    except Exception as e:
        return {'valid': False, 'error': f'PDF 损坏: {e}'}
```

### 2. PDF 类型检测 (文本 vs 扫描)

```python
def detect_pdf_type(pdf_path, sample_pages=5):
    """
    检测 PDF 是文本型还是扫描型

    方法: 抽样几页，尝试提取文字
    - 如果能提取到大量文字 → 文本型
    - 如果几乎没有文字 → 扫描型
    - 如果部分页有、部分没有 → 混合型

    返回:
    {
        'type': 'text' | 'scanned' | 'mixed',
        'text_pages': 380,      # 有文字层的页数
        'image_pages': 32,      # 纯图片页数
        'text_ratio': 0.92,     # 文字页比例
        'sample_text': '...'    # 抽样文字 (用于语言检测)
    }
    """
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)

    # 抽样页码 (首、中、尾)
    sample_indices = [0, total_pages//4, total_pages//2,
                      3*total_pages//4, total_pages-1]

    text_pages = 0
    sample_text = ""

    for i in sample_indices:
        page = reader.pages[i]
        text = page.extract_text() or ""

        # 如果提取到超过 100 字符，认为有文字层
        if len(text.strip()) > 100:
            text_pages += 1
            sample_text += text[:500]

    ratio = text_pages / len(sample_indices)

    if ratio > 0.8:
        pdf_type = 'text'
    elif ratio < 0.2:
        pdf_type = 'scanned'
    else:
        pdf_type = 'mixed'

    return {
        'type': pdf_type,
        'text_ratio': ratio,
        'sample_text': sample_text
    }
```

### 3. 图像质量评估

```python
def assess_image_quality(pdf_path, sample_pages=3):
    """
    评估扫描质量 (针对扫描型 PDF)

    检查项:
    - 分辨率/DPI
    - 是否模糊
    - 是否有倾斜
    - 对比度

    返回:
    {
        'quality': 'high' | 'medium' | 'low',
        'estimated_dpi': 150,
        'issues': ['分辨率偏低', '部分页面模糊'],
        'recommendation': '建议使用 DPI 200 处理'
    }
    """
    # 转换几页为图片，分析质量
    images = convert_from_path(pdf_path, first_page=1, last_page=3)

    quality_scores = []
    for img in images:
        # 分辨率检查
        width, height = img.size
        # A4 纸张 8.5x11 inch，150 DPI 应该是 1275x1650
        estimated_dpi = width / 8.5

        # 清晰度检查 (使用 Laplacian 方差)
        gray = img.convert('L')
        laplacian_var = calculate_laplacian_variance(gray)

        quality_scores.append({
            'dpi': estimated_dpi,
            'sharpness': laplacian_var
        })

    # 综合评估
    avg_dpi = sum(s['dpi'] for s in quality_scores) / len(quality_scores)

    if avg_dpi >= 200:
        quality = 'high'
    elif avg_dpi >= 120:
        quality = 'medium'
    else:
        quality = 'low'

    return {'quality': quality, 'estimated_dpi': avg_dpi, ...}
```

### 4. 语言检测

```python
def detect_language(sample_text):
    """
    检测文档主要语言

    方法: 统计字符分布
    - 中文字符占比
    - 英文字符占比
    - 其他字符

    返回:
    {
        'primary_language': 'zh' | 'en' | 'mixed',
        'chinese_ratio': 0.65,
        'english_ratio': 0.30,
        'confidence': 0.85
    }
    """
    if not sample_text:
        return {'primary_language': 'unknown'}

    # 统计字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', sample_text))
    english_chars = len(re.findall(r'[a-zA-Z]', sample_text))
    total_chars = len(sample_text)

    zh_ratio = chinese_chars / total_chars if total_chars else 0
    en_ratio = english_chars / total_chars if total_chars else 0

    if zh_ratio > 0.5:
        lang = 'zh'
    elif en_ratio > 0.5:
        lang = 'en'
    else:
        lang = 'mixed'

    return {
        'primary_language': lang,
        'chinese_ratio': zh_ratio,
        'english_ratio': en_ratio
    }
```

### 5. 成本预估

```python
def estimate_cost(pdf_results):
    """
    预估处理成本

    基于:
    - 总页数
    - PDF 类型 (扫描型需要更多处理)
    - qwen-vl-plus 定价: ¥0.0015/千token (输入)

    返回:
    {
        'total_pages': 1250,
        'estimated_tokens': 2_500_000,
        'estimated_cost_rmb': 3.75,
        'estimated_time_minutes': 25,
        'breakdown': [
            {'pdf': 'book1.pdf', 'pages': 400, 'cost': 1.20},
            {'pdf': 'book2.pdf', 'pages': 850, 'cost': 2.55},
        ]
    }
    """
    # 每页估算 token
    # - 图片: ~1280 tokens (固定)
    # - Prompt: ~500 tokens
    # - OCR 文本: ~500 tokens
    # 总计约 2000-2500 tokens/页

    TOKENS_PER_PAGE = 2000
    PRICE_PER_1K_TOKENS = 0.0015  # qwen-vl-plus
    PAGES_PER_MINUTE = 40  # 基于实际测试

    total_pages = sum(p['page_count'] for p in pdf_results)
    total_tokens = total_pages * TOKENS_PER_PAGE
    total_cost = (total_tokens / 1000) * PRICE_PER_1K_TOKENS
    total_time = total_pages / PAGES_PER_MINUTE

    return {
        'total_pages': total_pages,
        'estimated_tokens': total_tokens,
        'estimated_cost_rmb': round(total_cost, 2),
        'estimated_time_minutes': round(total_time, 1),
        ...
    }
```

---

## 用户界面输出

```
====================================================================
                    DocMind 0.8 - 预检查报告
====================================================================

📁 扫描目录: ./input
📄 发现 PDF: 5 个

┌─────────────────────────────────────────────────────────────────┐
│ 文件检查结果                                                    │
├──────────────────────────┬──────┬──────────┬──────┬─────────────┤
│ 文件名                   │ 页数 │ 类型     │ 语言 │ 状态        │
├──────────────────────────┼──────┼──────────┼──────┼─────────────┤
│ economics_textbook.pdf   │ 412  │ 扫描型   │ 英文 │ ✅ 可处理   │
│ research_paper.pdf       │ 28   │ 文本型   │ 混合 │ ✅ 可处理   │
│ annual_report.pdf        │ 156  │ 混合型   │ 中文 │ ✅ 可处理   │
│ encrypted_doc.pdf        │ -    │ -        │ -    │ ❌ 已加密   │
│ corrupted_file.pdf       │ -    │ -        │ -    │ ❌ 文件损坏 │
└──────────────────────────┴──────┴──────────┴──────┴─────────────┘

⚠️  警告:
   - encrypted_doc.pdf: 需要密码才能打开
   - corrupted_file.pdf: 文件损坏，无法读取

📊 成本预估:
   ├── 可处理页数: 596 页
   ├── 预估 Token: 1,192,000
   ├── 预估费用: ¥1.79
   └── 预估时间: ~15 分钟

====================================================================
是否继续处理? (跳过 2 个问题文件)

[Y] 继续  [N] 取消  [S] 查看详情
>
```

---

## 输出文件格式

```json
// preflight_report.json
{
  "scan_time": "2024-12-03T14:30:00",
  "input_dir": "./input",
  "summary": {
    "total_files": 5,
    "processable": 3,
    "skipped": 2,
    "total_pages": 596,
    "estimated_cost_rmb": 1.79,
    "estimated_time_minutes": 15
  },
  "files": [
    {
      "name": "economics_textbook.pdf",
      "status": "ok",
      "page_count": 412,
      "pdf_type": "scanned",
      "language": "en",
      "quality": "medium",
      "estimated_cost": 1.24
    },
    {
      "name": "encrypted_doc.pdf",
      "status": "error",
      "error": "PDF 已加密，需要密码",
      "skip_reason": "encrypted"
    }
  ]
}
```

---

## run.sh 集成方案

```bash
# Step 0: Pre-flight Check
echo "Step 0: 预检查..."
python3 scripts/preflight_check.py \
    --input "$INPUT_DIR" \
    --report "$LOGS_DIR/preflight_report.json"

# 检查是否有可处理的文件
PROCESSABLE=$(python3 -c "
import json
with open('$LOGS_DIR/preflight_report.json') as f:
    data = json.load(f)
print(data['summary']['processable'])
")

if [ "$PROCESSABLE" -eq 0 ]; then
    echo "❌ 没有可处理的 PDF 文件"
    exit 1
fi

# 显示成本预估，等待确认 (可选)
if [ "$SKIP_CONFIRM" != "true" ]; then
    python3 scripts/preflight_check.py --show-summary
    read -p "是否继续? [Y/n] " confirm
    if [ "$confirm" = "n" ]; then
        exit 0
    fi
fi
```

---

## 依赖

- `pypdf` 或 `PyPDF2`: PDF 读取和文字提取
- `pdf2image`: 转换为图片 (质量评估)
- `Pillow`: 图像分析

---

## 实现优先级

1. **Phase 1**: 基础检查 (完整性 + 加密检测 + 页数统计)
2. **Phase 2**: 类型检测 + 语言检测
3. **Phase 3**: 质量评估 + 成本预估
4. **Phase 4**: 用户交互确认
