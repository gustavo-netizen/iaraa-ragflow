# DocMind 0.8 - PDF to Markdown Converter

A high-performance PDF to Markdown conversion system using Qwen-VL API with:
- Multi-API key load balancing (up to 8 keys)
- Smart PDF splitting (by page count + file size)
- Resume capability - continue from where you left off
- Concurrent processing (30 PDFs × 10 LLM calls = 300 concurrent, optimized for 6 keys)
- YAML metadata generation for figures/charts

## Requirements

- **Python**: >= 3.7
- **OS**: macOS / Linux (Windows users need WSL)
- **System**: poppler (for PDF rendering)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/haylenfoust-svg/DocMind.git
cd DocMind

# 2. Install system dependencies (poppler for PDF rendering)

# macOS
brew install poppler

# Ubuntu/Debian
sudo apt-get install poppler-utils

# Windows
# Download from: https://github.com/oschwartz10612/poppler-windows/releases
# Add bin/ folder to PATH

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Configure API keys (choose one method)

# Method A: Environment variables
cp .env.example .env
# Edit .env and add your Aliyun DashScope API keys

# Method B: Keys file (recommended for multiple keys)
cp api/keys.txt.example api/keys.txt
# Edit api/keys.txt and add your API keys (one per line)

# 5. Place PDFs in input/ directory
cp /path/to/your/*.pdf input/

# 6. Run
./run.sh
```

## API Key Configuration

**Priority order:** `api/keys.txt` > `.env` file > environment variables

### Option 1: Keys File (Recommended)
Create `api/keys.txt` with one key per line:
```
sk-your-api-key-1
sk-your-api-key-2
sk-your-api-key-3
# ... up to 8 keys
```

### Option 2: .env File
```bash
# Copy template and edit
cp .env.example .env

# Add your keys
DASHSCOPE_API_KEY_1=sk-xxx
DASHSCOPE_API_KEY_2=sk-xxx
# ... up to DASHSCOPE_API_KEY_8
```

### Option 3: Environment Variables
```bash
export DASHSCOPE_API_KEY_1='sk-xxx'
export DASHSCOPE_API_KEY_2='sk-xxx'
# ... up to DASHSCOPE_API_KEY_8
```

### Performance with Multiple Keys
Each Aliyun main account provides ~20 RPS. With 6 separate accounts (optimized):
- 6 accounts × 20 RPS = 120 RPS total capacity
- Default: 30 PDFs parallel × 10 LLM concurrent = 300 concurrent
- Per key: 50 concurrent, 11.1 RPS (8.9 RPS headroom)

## Resume Capability

Processing is automatically checkpointed. If interrupted:

```bash
# Continue from checkpoint (automatic)
./run.sh

# Check current progress
./run.sh --status

# Force restart from beginning
./run.sh --restart
```

## Directory Structure

```
DocMind0.8/
├── run.sh                  # Main entry script
├── .env.example            # API key template (env vars)
├── .gitignore              # Git ignore rules
├── README.md               # This file
├── requirements.txt        # Python dependencies
├── api/
│   └── keys.txt.example    # API key template (file-based)
├── scripts/
│   ├── docmind_converter.py      # Core PDF→MD converter
│   ├── progress_manager.py       # Resume/checkpoint manager
│   ├── split_large_pdfs_smart.py # Smart PDF splitting
│   ├── merge_results_full.py     # Result merging
│   ├── retry_failed_pages.py     # Retry failed pages
│   ├── postprocess.py            # Markdown post-processing
│   ├── generate_quality_report.py # KQI metrics (thin shim → validation/)
│   ├── final_delivery_check.py   # Output validation (thin shim → validation/)
│   └── admin/                    # Utilities (monitor, archive, audit, recovery)
├── docmind/                # Stage-1 split: api_key_pool, qwen_client, page_processor, pipeline, retry, document
├── validation/             # Pluggable checkers + cost + report (Fase F.2)
├── input/                  # Place PDFs here
├── output/                 # Processing output (auto-generated)
├── final-delivery/         # Clean output (1 folder per book)
└── logs/                   # Processing logs
```

## Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                     DocMind Processing Flow                     │
└─────────────────────────────────────────────────────────────────┘

Step 1: Smart Split
├── Large PDFs (>50 pages or >50MB) → Split into chunks
└── Small PDFs → Direct processing queue

Step 2: Process Chunks (30 PDFs parallel)
├── Phase 1: PDF → Images (150 DPI)
├── Phase 2: OCR extraction (20 concurrent)
└── Phase 3: LLM processing (10 concurrent per PDF)

Step 3: Process Small PDFs
└── Same 3-phase processing

Step 4: Merge Results
├── Combine chunks back to original PDFs
└── Adjust page numbers automatically

Step 5: Final Delivery
└── Clean output: BookName.md + BookName.yaml + BookName.footnotes.yaml
```

## Command Line Options

```bash
./run.sh [options]

Options:
  --restart       Force restart, ignore previous progress
  --status        Show current progress only
  --retry-failed  Retry previously failed pages only
  --help, -h      Show help

Environment:
  MAX_PAGES=50    Max pages per chunk (default: 50)
  MAX_SIZE=50     Max MB per chunk (default: 50)
  SEMAPHORE=30    Concurrent PDFs (default: 30, optimized for 6 keys)
  LLM_CONCURRENT=10  LLM calls per PDF (default: 10, optimized for 6 keys)
```

## Output Format

Each PDF generates:
- `*.md` — Markdown content with page markers (`<!-- Page X -->`)
- `*_all_figures.yaml` — Figure/chart metadata
- `*.footnotes.yaml` — Footnotes sidecar (Fase J / [ADR-0004](../docs/adr/0004-footnotes-sidecar-yaml.md)). Schema flat `notes: [{page, id, text}]`; emissão incondicional (`notes: []` quando vazio). Body MD pós-J.2 não contém mais blocos `**Footnotes:**`; o metadata header ganha um marker `*Footnotes: sidecar*` quando há notes. `book_converter` opcionalmente renderiza `## Notas` via flag `inline_notes` (`none`/`useful`/`all`).

## API Requirements

- **Provider**: Aliyun DashScope
- **Model**: qwen-vl-plus
- **Get API Key**: https://dashscope.console.aliyun.com/
- **Rate Limit**: ~20 RPS per main account, ~1,200 RPM
- **Recommendation**: Use multiple keys from different main accounts

## Notes

- Large PDFs (>50 pages or >50MB) are auto-split
- Page numbers are auto-adjusted during merge
- DPI set to 150 for optimal quality/size balance
- Progress saved in `progress.json` (auto-generated, gitignored)

## Version History

### v0.8
- Multi-API key support (up to 8 keys, optimized for 6 keys)
- File-based API key loading (`api/keys.txt`)
- Optimized concurrency (30 PDFs × 10 LLM = 300 concurrent)
- Resume capability with page-level checkpoints
- Final-delivery folder generation
- Renamed to DocMind for general-purpose use

### v0.7
- Initial version
- Smart PDF splitting
- Concurrent processing
- Result merging
