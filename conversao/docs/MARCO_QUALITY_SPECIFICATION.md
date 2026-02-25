# Marco Quality Specification & Requirements

> **Note**: This document consolidates all Marco quality standards, YAML schema requirements, and processing specifications gathered from the project documentation. It serves as the definitive reference for PDF-to-Markdown conversion quality compliance.

**Document Version**: 1.0
**Created**: 2025-12-03
**Source Files**:
- `marco_compliant_converter.py`
- `DocGrok-MCP1128/docs/FEATURE_SPEC.md`
- `PADDLEOCR_MARCO_QUALITY_TEST_REPORT.md`
- `COMPLETE_ISSUES_LIST.md`
- `EXECUTIVE_REPORT.md`

---

## Table of Contents

1. [YAML Metadata Structure (Core Schema)](#1-yaml-metadata-structure-core-schema)
2. [Key Quality Indicators (KQI)](#2-key-quality-indicators-kqi)
3. [Output Format Specifications](#3-output-format-specifications)
4. [Processing Pipeline Requirements](#4-processing-pipeline-requirements)
5. [Validation Report Structure](#5-validation-report-structure)
6. [Prompt Engineering Guidelines](#6-prompt-engineering-guidelines)
7. [Known Issues & Fixes](#7-known-issues--fixes)
8. [Quality Checklist](#8-quality-checklist)

---

## 1. YAML Metadata Structure (Core Schema)

Every detected figure/chart/table MUST generate a structured YAML metadata file with the following fields:

### 1.1 Complete YAML Schema

```yaml
# ============================================================
# MARCO COMPLIANT YAML SCHEMA FOR FIGURES/CHARTS/TABLES
# ============================================================

# SECTION 1: Chart Identification (REQUIRED)
chart_identification:
  chart_title: "Revenue Growth 2020-2024"           # Specific title from figure
  figure_number: "Figure 3"                          # Extracted figure number
  figure_reference_in_text: "Figure 3"               # How it's referenced in text
  page_number: 15                                    # Page where figure appears
  image_type: "data_visualization"                   # See image_type values below
  chart_type: "line_chart"                           # See chart_type values below

# SECTION 2: Visual Content (REQUIRED)
visual_content:
  content_description: "Line chart showing quarterly revenue growth from Q1 2020 to Q4 2024, with actual revenue (blue line) compared against targets (dashed red line). Revenue exceeded targets in Q2-Q4 2024."
  key_elements:
    - "Revenue line (blue)"
    - "Target line (dashed red)"
    - "Quarterly markers"
  text_labels:
    - "Q1 2020"
    - "Q4 2024"
    - "Revenue ($M)"
  content_summary: "Revenue exceeded targets in Q2-Q4 2024"  # Max 200 chars
  key_insight: "15% YoY growth achieved"

# SECTION 3: Data Extraction (REQUIRED for data charts)
data_extraction:
  axes:
    x_axis:
      label: "Quarter"
      unit: null                                     # null if categorical
      range: ["Q1 2020", "Q4 2024"]
      scale: "categorical"                           # categorical, linear, log
    y_axis:
      label: "Revenue"
      unit: "$M"
      range: [0, 150]
      scale: "linear"
  data_series:
    - series_name: "Actual Revenue"
      data_points:
        - {x: "Q1 2020", y: 45}
        - {x: "Q2 2020", y: 52}
        - {x: "Q3 2020", y: 58}
        - {x: "Q4 2020", y: 63}
      trend: "upward"                                # upward, downward, stable, fluctuating
    - series_name: "Target"
      data_points:
        - {x: "Q1 2020", y: 40}
        - {x: "Q2 2020", y: 48}

# SECTION 4: Statistical Information (IF AVAILABLE)
statistical_information:
  correlation: "0.90"                                # Correlation coefficient
  equation: "y = 0.3301x + 0.0019"                   # Trend line equation
  r_squared: "0.81"                                  # R-squared value
  sample_size: 93                                    # Number of data points
  growth_rate: "15% YoY"                             # Growth rate if applicable

# SECTION 5: Visual Design (REQUIRED)
visual_design:
  color_scheme: ["#0066CC", "#CC0000", "#666666"]
  has_grid: true
  legend_position: "top_right"                       # top_right, bottom, none, etc.
  special_annotations:
    - "Target line"
    - "Growth annotation"

# SECTION 6: Quality Check (REQUIRED)
quality_check:
  data_completeness:
    all_labels_readable: "yes"                       # yes, partial, no
    all_values_extracted: "yes"                      # yes, no
    uncertainties: []                                # List of uncertain extractions
    total_data_points_visible: 20
  extraction_confidence: "high"                      # high, medium, low
  validation_checklist:
    figure_number_found: "✓"                         # ✓ or ✗
    image_type_identified: "✓"
    all_axes_labeled: "✓"
    data_points_extracted: "✓"
    manual_verification_needed: "✗"
```

### 1.2 Allowed Values

#### image_type Values
| Value | Description |
|-------|-------------|
| `data_visualization` | Charts, graphs with quantitative data |
| `conceptual_diagram` | Flowcharts, process diagrams, organizational charts |
| `mathematical_model` | Equations, formulas, mathematical representations |
| `table` | Structured tabular data |
| `mixed` | Combination of multiple types |
| `photograph` | Photographic images |
| `map` | Geographic or spatial representations |

#### chart_type Values
| Value | Description |
|-------|-------------|
| `scatter_plot` | X-Y scatter plots |
| `bar_chart` | Vertical or horizontal bar charts |
| `line_chart` | Line graphs |
| `pie_chart` | Pie or donut charts |
| `area_chart` | Area charts |
| `histogram` | Frequency distributions |
| `box_plot` | Box and whisker plots |
| `heatmap` | Heat maps |
| `flowchart` | Process flow diagrams |
| `data_table` | Tabular data |
| `organizational_chart` | Org charts |
| `timeline` | Timeline visualizations |
| `network_diagram` | Network/graph visualizations |

---

## 2. Key Quality Indicators (KQI)

### 2.1 Primary Quality Metrics

| Metric | Standard Requirement | Description |
|--------|---------------------|-------------|
| **YAML Insertion Rate** | ≥95% | Percentage of figures with correctly linked YAML in Markdown |
| **Average Confidence** | ≥0.85 | Mean extraction confidence across all figures |
| **Figure Detection Completeness** | ≥85% | Detected figures / Actual figures in document |
| **Processing Success Rate** | ≥95% | Pages successfully processed / Total pages |
| **OCR Accuracy Rate** | ≥90% | Character recognition accuracy |

### 2.2 Confidence Distribution Requirements

| Confidence Level | Threshold | Maximum Allowed |
|-----------------|-----------|-----------------|
| **High Confidence** | >0.9 | ≥70% of all figures |
| **Medium Confidence** | 0.6-0.9 | ≤25% of all figures |
| **Low Confidence** | <0.6 | ≤5% of all figures |

### 2.3 Quality Grades

| Grade | Score Range | Description |
|-------|-------------|-------------|
| **A+** | 95-100 | Exceeds all requirements |
| **A** | 90-94 | Meets all requirements |
| **B** | 80-89 | Minor issues, acceptable |
| **C** | 70-79 | Needs improvement |
| **D** | 60-69 | Significant issues |
| **F** | <60 | Does not meet requirements |

---

## 3. Output Format Specifications

### 3.1 Directory Structure

```
document_name/
├── document_name.md                    # Main Markdown file
├── document_name_all_figures.yaml      # Combined YAML for all figures
├── document_name.validation.yaml       # Validation report
├── images/
│   ├── page_001.png                    # Page images (DPI 200)
│   ├── page_002.png
│   └── ...
└── yaml_metadata/
    ├── Figure_1_page1.yaml             # Individual figure YAML
    ├── Figure_2_page3.yaml
    ├── Table_1_page5.yaml
    └── ...
```

### 3.2 Markdown Format Requirements

```markdown
# Document Title

*Processed with Marco-Compliant Converter on YYYY-MM-DD HH:MM:SS*

*Model: qwen-vl-max*

*Total Figures Detected: N*

*Total Tables Detected: M*

---

## Page 1

### Figure 1: Chart Title Here

![Figure 1: Chart Title Here](images/page_001.png)

*YAML Metadata: [yaml_metadata/Figure_1_page1.yaml](yaml_metadata/Figure_1_page1.yaml)*

Body text content for this page goes here. This should be the main text
excluding figure-related content to avoid duplication.

---

## Page 2

Body text content without figures...

| Column A | Column B | Column C |
|----------|----------|----------|
| Data 1   | Data 2   | Data 3   |

*Table extracted from page 2*

---

## Page 3

### Figure 2: Another Chart

![Figure 2: Another Chart](images/page_003.png)

*YAML Metadata: [yaml_metadata/Figure_2_page3.yaml](yaml_metadata/Figure_2_page3.yaml)*

More body text...
```

### 3.3 Naming Conventions

| File Type | Pattern | Example |
|-----------|---------|---------|
| Page Image | `page_NNN.png` | `page_001.png`, `page_042.png` |
| Figure YAML | `{FigureRef}_page{N}.yaml` | `Figure_1_page1.yaml` |
| Table YAML | `Table_{N}_page{P}.yaml` | `Table_3_page15.yaml` |
| Combined YAML | `{document}_all_figures.yaml` | `research_paper_all_figures.yaml` |
| Validation | `{document}.validation.yaml` | `research_paper.validation.yaml` |

---

## 4. Processing Pipeline Requirements

### 4.1 Five-Phase Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Marco Five-Phase Processing Pipeline                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Phase 1          Phase 2           Phase 3         Phase 4    Phase 5  │
│  ─────────        ─────────         ─────────       ─────────  ─────────│
│                                                                         │
│  ┌─────────┐     ┌─────────────┐   ┌─────────┐    ┌─────────┐ ┌───────┐│
│  │ PDF     │     │ Smart       │   │ Cloud   │    │ Cloud   │ │ Valid-││
│  │ → Image │ ──▶ │ Chunking    │ ──▶│ OCR     │ ──▶│ LLM     │─▶│ ation ││
│  │ (Local) │     │ Analysis    │   │ Extract │    │ Process │ │Report ││
│  └─────────┘     └─────────────┘   └─────────┘    └─────────┘ └───────┘│
│       │                │                │              │           │    │
│       ▼                ▼                ▼              ▼           ▼    │
│   PNG images      Chunking         OCR text      JSON/YAML    .md      │
│   (DPI 200)       strategy         (3-page       metadata     .yaml    │
│                   cost estimate    context)                   .valid   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Three-Page Context Window (CRITICAL)

The three-page context window is essential for:
- Identifying unlabeled figures referenced in adjacent pages
- Understanding cross-page references
- Extracting complete figure captions

```python
# Implementation Pattern
context_info = f"""
### THREE-PAGE CONTEXT WINDOW

**PREVIOUS PAGE (Page {page_num - 1}) - FOR CONTEXT ONLY:**
{prev_ocr if prev_ocr else "N/A (First page)"}

**CURRENT PAGE (Page {page_num}) - MUST PROCESS THIS PAGE:**
{current_ocr}

**NEXT PAGE (Page {page_num + 1}) - FOR CONTEXT ONLY:**
{next_ocr if next_ocr else "N/A (Last page)"}

---

IMPORTANT REMINDER:
- You must ONLY transcribe and process the CURRENT PAGE (Page {page_num})
- The previous and next page OCR are provided ONLY to help you:
  ✅ Identify figures (e.g., if prev page says "Figure 2 shows...", current page unlabeled chart might be Figure 2)
  ✅ Handle cross-page references
  ✅ Understand context for better figure caption extraction
- ❌ DO NOT transcribe content from previous or next pages
"""
```

### 4.3 Concurrency Configuration

| PDF Size | Chunk Size | OCR Concurrency | LLM Concurrency |
|----------|------------|-----------------|-----------------|
| Small (<20 pages) | No chunking | 20 | 10 |
| Medium (20-100 pages) | 20 pages/chunk | 20 | 10 |
| Large (100-500 pages) | 50 pages/chunk | 15 | 8 |
| Extra Large (>500 pages) | 100 pages/chunk | 10 | 5 |
| Figure-dense | Reduce by 50% | Reduce by 50% | Reduce by 50% |

### 4.4 Smart Chunking Rules

```python
# Dual-criteria chunking (pages AND file size)
def calculate_chunks(pdf_path, max_pages=300, max_size_mb=50):
    total_pages = get_page_count(pdf_path)
    file_size_mb = get_file_size_mb(pdf_path)

    chunks_by_pages = ceil(total_pages / max_pages)
    chunks_by_size = ceil(file_size_mb / max_size_mb)

    # Take the stricter limit (more chunks = smaller, safer)
    num_chunks = max(chunks_by_pages, chunks_by_size)
    return num_chunks
```

---

## 5. Validation Report Structure

### 5.1 Complete Validation Schema

```yaml
# document.validation.yaml
validation_report:
  # Document Information
  document_info:
    filename: "research_paper.pdf"
    total_pages: 85
    processed_pages: 85
    processing_date: "2024-11-27T12:00:00"
    model: "qwen-vl-max-latest"
    provider: "qwen"

  # Core Validation Metrics
  validation_metrics:
    yaml_insertion_rate: 0.98              # Target: ≥0.95
    average_confidence: 0.85               # Target: ≥0.85
    figure_detection_rate: 0.95            # Target: ≥0.85
    table_detection_rate: 0.92             # Target: ≥0.85

    # Detailed Statistics
    total_figures_detected: 35
    total_tables_detected: 12
    high_confidence_figures: 28            # >0.9
    medium_confidence_figures: 5           # 0.6-0.9
    low_confidence_figures: 2              # <0.6

    # Page Statistics
    pages_with_figures: 25
    pages_with_tables: 8
    pages_with_errors: 2

  # Quality Indicators (Boolean Checks)
  quality_indicators:
    all_figures_have_yaml: true
    all_tables_extracted: true
    zero_hallucination: true               # No fabricated content
    proper_markdown_format: true
    complete_data_extraction: true
    cross_reference_valid: true            # All internal links work

  # Error Log
  error_log:
    - page: 45
      error_type: "api_timeout"
      message: "API request timeout after 30s"
      retry_count: 3
      resolved: true

    - page: 67
      error_type: "json_parse_error"
      message: "Invalid JSON response"
      retry_count: 2
      resolved: true

  # Page-by-Page Results
  page_by_page_results:
    - page: 1
      success: true
      figure_count: 1
      table_count: 0
      confidence: 0.95
      processing_time: 2.3
      tokens: {input: 3500, output: 1200}

    - page: 2
      success: true
      figure_count: 0
      table_count: 1
      confidence: 0.88
      processing_time: 1.8
      tokens: {input: 2800, output: 900}
    # ... continues for all pages

  # Recommendations
  recommendations:
    - "Page 45-46 figures have low confidence, recommend manual review"
    - "Table_3 has merged cells, data may need adjustment"
```

---

## 6. Prompt Engineering Guidelines

### 6.1 Full Prompt (~2500 characters)

Use for: Normal academic documents, detailed figure data extraction

```python
llm_prompt = f"""{context_info}

TASK: Analyze CURRENT PAGE (Page {page_num}) and detect ALL visual elements:

1. **Detect ALL figures/charts/tables/diagrams** (100% detection rate):
   - Explicitly labeled: "Figure N:", "Fig. N:", "TABLE N:", "Chart N:", "Graph N:"
   - Implicitly referenced: "as shown below/above", "the following chart"
   - Orphaned captions (caption without visible figure)
   - Use context from prev/next pages to identify unlabeled figures

2. **For EACH detected figure, extract**:
   - Figure number and title
   - Image type: data_visualization, conceptual_diagram, mathematical_model, table, mixed
   - Chart type: scatter_plot, bar_chart, line_chart, pie_chart, flowchart, data_table, etc.
   - Detailed visual description (trends, patterns, key insights)
   - ALL visible text labels
   - Key elements list

3. **If it's a DATA chart, also extract**:
   - Axes information (labels, units, ranges)
   - Data points (use ~ for approximate values)
   - Trend lines and equations
   - Statistical info (correlation, R², sample size)

4. **Extract body text** (CURRENT PAGE ONLY):
   - Extract all text NOT part of figures
   - Maintain paragraph structure
   - Remove figure-related text to avoid duplication

Return JSON format:
{{
  "page_number": {page_num},
  "has_figures": true/false,
  "figure_count": N,
  "figures": [...],
  "body_text": "..."
}}

Return ONLY the JSON, no other text."""
```

### 6.2 Optimized Short Prompt (~500 characters)

Use for: Politically sensitive documents, avoiding content moderation triggers

```python
# Truncate context to reduce total input
prev_summary = prev_ocr[:100] + "..." if prev_ocr and len(prev_ocr) > 100 else prev_ocr
next_summary = next_ocr[:100] + "..." if next_ocr and len(next_ocr) > 100 else next_ocr
ocr_summary = ocr_text[:300] + "..." if len(ocr_text) > 300 else ocr_text

enhance_prompt = f"""Page {page_num} analysis:

OCR text: {ocr_summary}

Context:
- Previous page {page_num-1}: {prev_summary if prev_summary else 'N/A'}
- Next page {page_num+1}: {next_summary if next_summary else 'N/A'}

Extract:
1. All figures/tables with numbers and captions
2. Main body text (structured)
3. Footnotes, citations, page numbers
4. Mathematical formulas
5. Keep original language - DO NOT translate

Return JSON format:
{{
  "page_number": {page_num},
  "figures": [
    {{"figure_number": "Fig 1", "caption": "...", "type": "chart/table/diagram"}}
  ],
  "body_text": "main text content...",
  "footnotes": ["footnote 1", "footnote 2"],
  "page_markers": ["page numbers found in image"],
  "formulas": ["mathematical expressions"]
}}"""
```

### 6.3 Prompt Selection Criteria

| Condition | Use Full Prompt | Use Short Prompt |
|-----------|-----------------|------------------|
| Normal academic documents | ✓ | |
| Detailed data extraction needed | ✓ | |
| Complex visualizations | ✓ | |
| Politically sensitive content | | ✓ |
| Frequent DataInspectionFailed errors | | ✓ |
| Communist/revolutionary literature | | ✓ |
| High processing success rate needed | | ✓ |

---

## 7. Known Issues & Fixes

### 7.1 PDF Chunking Issues (All Fixed)

| Issue | Problem | Solution |
|-------|---------|----------|
| **A1: Wrong Page Numbers** | Chunk2+ MD files start from Page 1 | Adjust page numbers with offset |
| **A2: Wrong YAML page_number** | Individual YAML page_number not adjusted | Fix YAML page_number field |
| **A3: Incomplete YAML Paths** | MD missing chunk prefix in YAML links | Add chunk prefix to paths |
| **A4: Missing yaml_metadata/** | Folder not copied to final results | Copy and organize YAML files |
| **A5: Wrong all_figures page** | Merged YAML page field not adjusted | Adjust page fields with offset |
| **A6: Incomplete image paths** | all_figures.yaml missing chunk prefix | Add chunk prefix to image paths |
| **A7: Individual YAML paths** | image_path missing chunk prefix | Fix all YAML image paths |

### 7.2 Fix Implementation

```python
def merge_and_fix_chunks(chunks, final_dir):
    """Fix all 7 chunking issues during merge"""

    for chunk in chunks:
        offset = chunk['page_offset']
        chunk_name = chunk['name']

        # A1: Adjust page numbers in MD
        content = re.sub(
            r'## Page (\d+)',
            lambda m: f"## Page {int(m.group(1)) + offset}",
            content
        )

        # A2: Fix YAML page_number
        for yaml_file in chunk['yaml_files']:
            data = yaml.safe_load(yaml_file)
            data['chart_identification']['page_number'] += offset
            yaml.dump(data, yaml_file)

        # A3: Adjust YAML reference paths in MD
        content = re.sub(
            r'\(yaml_metadata/([^/\)]+)\)',
            rf'(yaml_metadata/{chunk_name}/\1)',
            content
        )

        # A4: Copy yaml_metadata folder
        shutil.copytree(
            chunk_dir / 'yaml_metadata',
            final_dir / 'yaml_metadata' / chunk_name
        )

        # A5: Adjust all_figures.yaml page numbers
        all_figures = re.sub(
            r'page: (\d+)',
            lambda m: f"page: {int(m.group(1)) + offset}",
            all_figures
        )

        # A6: Adjust image paths in all_figures.yaml
        all_figures = re.sub(
            r'path: "images/([^"]+)"',
            rf'path: "images/{chunk_name}/\1"',
            all_figures
        )

        # A7: Fix individual YAML image paths
        for yaml_file in chunk['yaml_files']:
            content = re.sub(
                r'image_path: images/([^/\n]+)',
                rf'image_path: images/{chunk_name}/\1',
                content
            )
```

---

## 8. Quality Checklist

### 8.1 Pre-Processing Checklist

- [ ] API keys configured correctly
- [ ] Input PDFs accessible and readable
- [ ] Output directory exists and writable
- [ ] Sufficient disk space (estimate: 10x PDF size)
- [ ] DPI set to 200 (or higher for complex documents)
- [ ] Concurrency configured based on PDF size

### 8.2 Post-Processing Checklist

- [ ] All pages processed successfully (check validation report)
- [ ] YAML insertion rate ≥95%
- [ ] Average confidence ≥0.85
- [ ] No pages with errors (or all errors resolved)
- [ ] All figure YAML files exist in yaml_metadata/
- [ ] All image files exist in images/
- [ ] Markdown links are valid (no 404s)
- [ ] Page numbers are continuous and correct
- [ ] For split PDFs: all 7 chunking issues verified fixed

### 8.3 Quality Audit Sampling

For large batches, perform random sampling:

```python
# Recommended sampling strategy
def audit_sample(total_pdfs, sample_rate=0.1, min_samples=5, max_samples=20):
    sample_size = max(min_samples, min(max_samples, int(total_pdfs * sample_rate)))
    return random.sample(range(total_pdfs), sample_size)

# For each sampled PDF, verify:
# 1. Open MD file, check formatting
# 2. Click 3-5 random YAML links, verify they open
# 3. Check page numbers at chunk boundaries
# 4. Verify figure detection matches visual inspection
```

---

## Appendix A: API Pricing Reference

| Provider | Model | Input (per 1K tokens) | Output (per 1K tokens) |
|----------|-------|----------------------|------------------------|
| Qwen | qwen-vl-plus | ¥0.0008 | ¥0.002 |
| Qwen | qwen-vl-max | ¥0.003 | ¥0.006 |
| OpenAI | gpt-4o | $0.0025 | $0.01 |
| OpenAI | gpt-4o-mini | $0.00015 | $0.0006 |
| DeepSeek | deepseek-chat | ¥0.001 | ¥0.002 |

## Appendix B: Error Codes Reference

| Error Code | Description | Solution |
|------------|-------------|----------|
| `DataInspectionFailed` | Content moderation triggered | Use short prompt, reduce context |
| `429 Rate Limit` | TPM exceeded | Reduce concurrency, add delays |
| `Timeout` | API response timeout | Increase timeout, retry |
| `InvalidJSON` | LLM returned malformed JSON | Retry, adjust prompt |
| `NoneType` | Empty API response | Check API key, retry |

---

**Document End**

*This specification is maintained by the Marco Team. For updates or corrections, please refer to the source code and project documentation.*
