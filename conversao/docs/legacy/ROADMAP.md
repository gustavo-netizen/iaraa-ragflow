# DocMind Improvement Roadmap

> 40+ improvement suggestions organized by priority and category
>
> **Last Updated**: 2024-12-03
> **Reference**: See `COMPLETE_PIPELINE.md` for detailed flow analysis

---

## ✅ Recently Completed (2024-12-03)

| Issue | Description | Commit | Status |
|-------|-------------|--------|--------|
| NEW-2 | Quality Report Generation (质量报告生成) | Pending | ✅ Done |
| NEW-5 | Resource Monitor Module (硬件资源监控) | Pending | ✅ Done |
| #4 | Tiered Retry Strategy (4次重试, 指数退避) | `6500450` | ✅ Done |
| #5 | API Key Health Monitoring (自动禁用故障key) | `6500450` | ✅ Done |
| #6 | Resume Validation Enhancement (验证MD文件存在性) | `f41f832` | ✅ Done |
| - | Merge Script Fix (缺失检测, 不再静默跳过) | 之前 | ✅ Done |
| - | JSON Escape Fix (LaTeX反斜杠处理) | 之前 | ✅ Done |
| - | YAML Schema Enhancement (MARCO规范) | 之前 | ✅ Done |

---

## 🆕 Pipeline Gaps Identified (基于 MinerU/Marker 最佳实践)

### NEW-1. [P0] Pre-flight Check Module ⭐ HIGH PRIORITY
**Gap**: 处理前无验证
**设计文档**: `DESIGN_PREFLIGHT_CHECK.md`
```
检查项:
1. PDF完整性 (损坏/加密检测)
2. PDF类型 (文本型/扫描型/混合型)
3. 图像质量评估 (DPI/清晰度)
4. 语言检测 (中/英/混合)
5. 成本预估 (页数→Token→费用)
6. 用户确认 (显示摘要后继续)
```

### ~~NEW-2. [P0] Quality Report Generation~~ ✅ DONE
**已实现**: `scripts/generate_quality_report.py`
- 执行摘要 (成功率/失败率/耗时/费用)
- 质量评分 (0-100分)
- 内容分析 (空页/短内容/长内容分布)
- 图表统计 (表格/公式/图片数量)
- 问题列表 (失败原因/需人工复核)
- MARCO规范符合度
- 已集成到 `run.sh` Step 6

### ~~NEW-3. [P1] Post-processing Module~~ ✅ DONE
**已实现**: `scripts/postprocess.py`
- 表格对齐修复
- 空行合并
- 标题层级标准化
- LaTeX公式验证
- 链接有效性检查 (可选)
- 自动生成目录 (可选)
- 已集成到 `run.sh` Step 6

### NEW-4. [P1] Integrity Check Module
**Gap**: 无输出完整性验证
```python
# scripts/integrity_check.py
- 页数对比 (原PDF vs 输出)
- 文件校验和 (checksum)
- 输出目录结构验证
```

### ~~NEW-5. [P1] Resource Monitor Module~~ ✅ DONE
**已实现**: `scripts/resource_monitor.py`
- CPU 使用率监控 (整体/进程)
- 内存占用监控 (进程内存/系统内存/峰值记录)
- 磁盘 I/O 监控 (读写速度 MB/s)
- 网络 I/O 监控 (上传/下载速度 KB/s)
- 进程信息 (线程数/子进程数/文件句柄)
- 后台线程定时采样 (默认10秒)
- 峰值记录和最终摘要报告
- 已集成到 `docmind_converter.py` 和 `generate_quality_report.py` (Section 8)

---

## Priority Legend

| Tag | Meaning | Timeline |
|-----|---------|----------|
| P0 | Must Have | Next Release |
| P1 | Should Have | Near-term |
| P2 | Nice to Have | Long-term |

---

## 1. Architecture

### 1. [P0] Configuration Management System
Current config is scattered across environment variables, .env, keys.txt, and hardcoded values. Unify into YAML:

```yaml
# config.yaml
processing:
  dpi: 150
  max_pages_per_chunk: 300
  max_size_mb: 50

concurrency:
  pdf_parallel: 10
  llm_concurrent: 12
  ocr_concurrent: 20

output:
  formats: [markdown, yaml]
  include_page_markers: true
```

### 2. [P2] Plugin-based Output Formats
Support multiple output formats:
- HTML (with embedded images)
- DOCX (Word documents)
- JSON (structured data)
- LaTeX (academic papers)

### 3. [P0] Cost Estimator
Before processing, scan all PDFs and estimate:
- Total pages / expected token consumption
- Estimated cost (based on qwen-vl-plus pricing)
- Estimated processing time
- Require user confirmation before starting

---

## 2. Reliability

### 4. [P1] Tiered Retry Strategy
Improve current simple retry logic:
- 1st failure: Immediate retry (transient network issue)
- 2nd failure: Wait 5 seconds, then retry
- 3rd failure: Switch API key, then retry
- 4th failure: Lower DPI, then retry
- Final failure: Log detailed error, continue with other pages

### 5. [P1] API Key Health Monitoring
- Track success rate, latency, and remaining quota per key in real-time
- Auto-disable faulty keys (e.g., after 5 consecutive failures)
- Recovery detection (periodically test disabled keys)

### 6. [P2] Enhanced Checkpoint/Resume
Currently page-level. Can be refined to:
- Phase-level (PDF→images, OCR, LLM as separate phases)
- Cross-machine resume support (store progress in Redis/SQLite)

---

## 3. User Experience

### 7. [P1] Real-time Progress Dashboard
Use Rich library for terminal TUI:

```
DocMind 0.8 - Processing Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Book1.pdf    [████████░░] 80%  320/400 pages
Book2.pdf    [██░░░░░░░░] 20%   50/250 pages
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Speed: 45 pages/min | ETA: 12 min
API Keys: 8 active | Errors: 3
Cost: ¥2.50 (estimated total: ¥8.00)
```

### 8. [P1] Pre-processing Quality Check
Auto-detect before processing:
- Is PDF encrypted/corrupted?
- Is it a scanned document (image-only) or has text layer?
- Image quality assessment
- Language detection (Chinese/English/mixed)

### 9. [P2] Post-processing Quality Report
Generate report after processing:
- Confidence score per page
- Number of detected figures/formulas
- List of pages that may need manual review
- Page count verification against original PDF

---

## 4. Scalability

### 10. [P2] Multi-model Support
Beyond qwen-vl-plus, support:
- GPT-4V (OpenAI)
- Claude Vision (Anthropic)
- Gemini Pro Vision (Google)
- Local models (e.g., LLaVA)

### 11. [P1] Docker Deployment
```dockerfile
FROM python:3.11-slim
COPY . /app
RUN pip install -r requirements.txt
ENTRYPOINT ["./run.sh"]
```

### 12. [P2] API Service Mode
Beyond CLI, provide REST API:
```bash
curl -X POST http://localhost:8000/convert \
  -F "file=@book.pdf" \
  -F "format=markdown"
```

---

## 5. Algorithm Optimization

### 13. [P2] Smart Chunking Strategy
Improve current fixed page/size splitting:
- Split by chapter boundaries (detect TOC structure)
- Split by content density (pages with many figures processed separately)
- Avoid breaking in the middle of tables/code blocks

### 14. [P2] Context-aware Processing
Currently each page is processed independently (already has 3-page context window with 100-char summary). Can enhance:
- Full previous/next page content (for cross-page content)
- Book-wide glossary building (unified terminology translation)
- Chapter heading hierarchy inference

### 15. [P1] Adaptive DPI
Currently fixed at 150 DPI. Adjust based on content:
- Text-only pages: 100 DPI (save processing time)
- Complex figures: 200 DPI (improve recognition accuracy)
- Small fonts/dense tables: 300 DPI

---

## 6. Quality Control

### 16. [P1] Output Validation Pipeline
- Markdown syntax validation (table closure, valid links)
- Math formula rendering test
- Chinese-English mixed text check
- Page number continuity verification

### 17. [P2] A/B Testing Framework
Compare different processing parameters:
- Different prompt templates
- Different DPI settings
- Different model versions
Auto-select optimal configuration.

### 18. [P2] Human Annotation Feedback Loop
- Mark incorrectly converted pages
- Collect corrected results
- Use for prompt optimization or model fine-tuning

---

## 7. Operations & Monitoring

### 19. [P0] Structured Logging System
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "pdf": "book.pdf",
  "page": 42,
  "phase": "llm",
  "api_key": "sk-xxx...xxx",
  "latency_ms": 1250,
  "tokens": 1500,
  "status": "success"
}
```
Enables ELK/Grafana analysis.

### 20. [P2] Alerting Mechanism
- Send notifications when error rate exceeds threshold (email/Slack/DingTalk)
- API quota depletion warning
- Processing speed anomaly alert

### 21. [P2] Historical Data Analysis
- Persist processing records (SQLite/PostgreSQL)
- Statistical reports: daily/weekly/monthly volume, cost, error rate
- Performance trend analysis

---

## 8. Security & Compliance

### 22. [P2] Sensitive Information Handling
- Auto-detect and mask (ID numbers, phone numbers, bank cards)
- Securely delete temporary files after processing
- Audit logs (who processed what files)

### 23. [P2] Access Control
- Tiered API key management (admin/regular user)
- Processing quota limits
- Operation audit logs

---

## 9. Ecosystem Integration

### 24. [P2] Knowledge Base Integration
Direct import of processed Markdown to:
- Notion
- Obsidian
- Confluence
- Vector databases (for RAG)

### 25. [P2] CI/CD Integration
- GitHub Action to auto-process PDFs in PRs
- Auto-update documentation repositories

### 26. [P2] Batch Task Scheduling
- Support scheduled tasks (cron)
- Task queues (Celery/RQ)
- Priority scheduling

---

## 10. Prompt Engineering

### 27. [P1] Prompt Template Management
Currently prompts are hardcoded. Change to:
- External `prompts/` directory for templates
- Multi-language prompts (Chinese prompts for Chinese books)
- Content-type specific optimization (academic papers, technical manuals, novels)

### 28. [P2] Dynamic Prompt Adjustment
Auto-switch based on page content:
- Table detected → Use table-specific prompt
- Code detected → Use code formatting prompt
- Math formula detected → Use LaTeX conversion prompt

### 29. [P2] Few-shot Example Library
Prepare high-quality examples for different scenarios:
```
prompts/
├── examples/
│   ├── table_example.md
│   ├── code_example.md
│   ├── formula_example.md
│   └── figure_example.md
```

---

## 11. Performance Optimization

### 30. [P1] Image Compression Optimization
Currently using 150 DPI PNG directly. Improvements:
- WebP format (30% smaller than PNG)
- Smart whitespace cropping
- Adjust color depth as needed (grayscale for text-only)

### 31. [P2] Streaming Processing
Currently loads entire PDF. For very large PDFs:
- Read and process incrementally
- Reduce memory footprint
- Support processing 10GB+ PDFs

### 32. [P1] Caching Mechanism
- OCR result cache (don't re-recognize identical images)
- API response cache (reuse during development/debugging)
- Chunk result cache (skip successful parts on retry)

---

## 12. Output Quality

### 33. [P1] Markdown Post-processing
- Auto-fix table alignment
- Merge consecutive empty lines
- Standardize heading hierarchy
- Link validity check

### 34. [P2] Enhanced Figure Extraction
Currently only records metadata. Improvements:
- Export images as separate files
- Figure OCR (extract text within figures)
- Figure description generation (use VLM for alt text)

### 35. [P1] Auto-generate Table of Contents
- Analyze heading structure
- Generate TOC with links
- Support multi-level nesting

---

## 13. Error Handling

### 36. [P0] Error Classification & Statistics
```
Error Summary:
├── API Errors: 12
│   ├── Rate Limit: 8
│   ├── Timeout: 3
│   └── Auth Failed: 1
├── Content Errors: 5
│   ├── Empty Page: 3
│   └── Corrupt Image: 2
└── System Errors: 1
    └── Disk Full: 1
```

### 37. [P1] Auto-repair Attempts
- Empty page → Skip and mark
- Corrupted image → Try re-rendering
- Garbled text detection → Switch OCR engine

### 38. [P2] Degradation Strategy
When high-quality processing fails:
1. First try qwen-vl-max (stronger model)
2. If fails, use qwen-vl-plus (current model)
3. If still fails, use pure OCR (no VLM enhancement)
4. Finally mark as needing manual processing

---

## 14. Testing & Documentation

### 39. [P1] Test Coverage
```
tests/
├── unit/
│   ├── test_api_key_rotation.py
│   ├── test_pdf_splitting.py
│   └── test_markdown_merge.py
├── integration/
│   └── test_full_pipeline.py
└── fixtures/
    ├── sample_1page.pdf
    └── sample_table.pdf
```

### 40. [P2] Benchmark Test Suite
- 10 representative PDFs (different types/difficulty levels)
- Ground truth (manually proofread Markdown)
- Auto-comparison scoring (BLEU/ROUGE)

---

## Implementation Roadmap

### Phase 1: Foundation (P0)
- [ ] Configuration management system
- [ ] Cost estimator
- [ ] Structured logging system
- [ ] Error classification & statistics

### Phase 2: Experience Enhancement (P1)
- [ ] Real-time progress dashboard
- [ ] Docker deployment
- [ ] Tiered retry strategy
- [ ] API key health monitoring
- [ ] Pre-processing quality check
- [ ] Adaptive DPI
- [ ] Output validation pipeline
- [ ] Prompt template management
- [ ] Image compression optimization
- [ ] Caching mechanism
- [ ] Markdown post-processing
- [ ] Auto-generate table of contents
- [ ] Auto-repair attempts
- [ ] Test coverage

### Phase 3: Advanced Features (P2)
- [ ] Plugin-based output formats
- [ ] Enhanced checkpoint/resume
- [ ] Post-processing quality report
- [ ] Multi-model support
- [ ] API service mode
- [ ] Smart chunking strategy
- [ ] Context-aware processing
- [ ] A/B testing framework
- [ ] Human annotation feedback loop
- [ ] Alerting mechanism
- [ ] Historical data analysis
- [ ] Sensitive information handling
- [ ] Access control
- [ ] Knowledge base integration
- [ ] CI/CD integration
- [ ] Batch task scheduling
- [ ] Dynamic prompt adjustment
- [ ] Few-shot example library
- [ ] Streaming processing
- [ ] Enhanced figure extraction
- [ ] Degradation strategy
- [ ] Benchmark test suite

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2024-01-15 | v0.8 | Initial roadmap with 40 improvement suggestions |
