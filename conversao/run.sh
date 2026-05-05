#!/bin/bash
# DocMind 0.8 - PDF to Markdown Converter
# Resume capable: continues from where it left off after interruption

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "DocMind 0.8 - PDF to Markdown 转换系统"
echo "======================================================================"

# 配置
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT_DIR="$SCRIPT_DIR/input"
OUTPUT_DIR="$SCRIPT_DIR/output"
SPLIT_DIR="$SCRIPT_DIR/input/split_pdfs"
LOGS_DIR="$SCRIPT_DIR/logs"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"
ADMIN_DIR="$SCRIPTS_DIR/admin"
PROGRESS_FILE="$SCRIPT_DIR/progress.json"
FINAL_DELIVERY="$SCRIPT_DIR/final-delivery"

# 参数处理
# Chunk 策略: 50页/chunk 平衡边界影响(4%)和并行效率
MAX_PAGES_PER_CHUNK=${MAX_PAGES:-50}
MAX_SIZE_MB=${MAX_SIZE:-50}

# 并发策略 (优化配置 - 6 API keys):
# - SEMAPHORE: 同时处理的 chunk 数量 (pdf_concurrency)
# - LLM_CONCURRENT: 每个 chunk 内的 VLM 并发数 (semaphore_limit)
# - 总并发 = 30 × 10 = 300 个 VLM 请求
# - 实测吞吐量: ~70-80 页/分钟 (6 keys, 瓶颈是API响应延迟3-6秒/页)
# - 配置适合6个API keys，每key 50并发，11.1 RPS，8.9 RPS headroom
# [测试记录: benchmark_config.md]
SEMAPHORE=${SEMAPHORE:-30}
LLM_CONCURRENT=${LLM_CONCURRENT:-10}

# 命令行参数
RESTART=false
STATUS_ONLY=false
RETRY_FAILED=false
TASK_NAME=""
MONITOR=false
LIST_HISTORY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --restart)
            RESTART=true
            shift
            ;;
        --status)
            STATUS_ONLY=true
            shift
            ;;
        --retry-failed)
            RETRY_FAILED=true
            shift
            ;;
        --task-name|-t)
            TASK_NAME="$2"
            shift 2
            ;;
        --monitor|-m)
            MONITOR=true
            shift
            ;;
        --history)
            LIST_HISTORY=true
            shift
            ;;
        --help|-h)
            echo ""
            echo "用法: ./run.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --restart         强制从头开始 (自动归档旧进度)"
            echo "  --status          仅显示当前进度状态"
            echo "  --retry-failed    仅重试之前失败的页面"
            echo "  --task-name, -t   设置任务名称 (用于监控和归档)"
            echo "  --monitor, -m     启用后台资源监控"
            echo "  --history         列出历史任务记录"
            echo "  --help, -h        显示此帮助信息"
            echo ""
            echo "环境变量:"
            echo "  MAX_PAGES         每块最大页数 (默认: 50)"
            echo "  MAX_SIZE          每块最大大小MB (默认: 50)"
            echo "  SEMAPHORE         PDF并发数 (默认: 30, 优化为6 keys)"
            echo "  LLM_CONCURRENT    每PDF的LLM并发数 (默认: 10, 优化为6 keys)"
            echo ""
            echo "示例:"
            echo "  ./run.sh --task-name lenin_21-30 --monitor    # 带监控的新任务"
            echo "  ./run.sh --restart --task-name batch2         # 重新开始新任务"
            echo "  ./run.sh --history                            # 查看历史记录"
            echo ""
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 列出历史记录
if [ "$LIST_HISTORY" = true ]; then
    python3 "$ADMIN_DIR/archive_progress.py" --list
    exit 0
fi

# 仅显示状态
if [ "$STATUS_ONLY" = true ]; then
    echo ""
    if [ -f "$PROGRESS_FILE" ]; then
        python3 "$SCRIPTS_DIR/progress_manager.py" --status --progress-file "$PROGRESS_FILE"
    else
        echo "没有找到进度文件，尚未开始处理"
    fi
    exit 0
fi

# 强制重新开始
if [ "$RESTART" = true ]; then
    echo ""
    echo -e "${YELLOW}⚠️  强制重新开始模式${NC}"

    # 归档旧进度 (如果存在)
    if [ -f "$PROGRESS_FILE" ]; then
        echo "   📦 归档旧进度..."
        if [ -n "$TASK_NAME" ]; then
            python3 "$ADMIN_DIR/archive_progress.py" --task-name "$TASK_NAME"
        else
            python3 "$ADMIN_DIR/archive_progress.py"
        fi
    fi

    # 删除进度文件 (如果归档失败也要删除)
    rm -f "$PROGRESS_FILE"
    rm -f "$PROGRESS_FILE.lock"

    # 删除分割目录
    rm -rf "$SPLIT_DIR"

    # 可选：删除输出目录（谨慎）
    # rm -rf "$OUTPUT_DIR"/*

    echo "   ✅ 已重置"
fi

# 自动生成任务名 (如果未指定)
if [ -z "$TASK_NAME" ]; then
    TASK_NAME="task_$(date +%Y%m%d_%H%M%S)"
fi
echo "任务名称: $TASK_NAME"

# 检查API Key配置
# Priority: 1) api/keys.txt  2) .env file  3) environment variable
API_KEYS_FILE="$SCRIPT_DIR/api/keys.txt"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$API_KEYS_FILE" ]; then
    # Count valid keys (non-empty, non-comment lines)
    KEY_COUNT=$(grep -v '^#' "$API_KEYS_FILE" | grep -v '^$' | wc -l | tr -d ' ')
    if [ "$KEY_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✅ API Keys 已配置: $KEY_COUNT 个 (from api/keys.txt)${NC}"
        # Export keys as environment variables for Python scripts
        KEY_INDEX=1
        while IFS= read -r KEY || [ -n "$KEY" ]; do
            # Skip empty lines and comments
            if [ -n "$KEY" ] && [[ ! "$KEY" =~ ^# ]]; then
                export "DASHSCOPE_API_KEY_$KEY_INDEX=$KEY"
                KEY_INDEX=$((KEY_INDEX + 1))
            fi
        done < "$API_KEYS_FILE"
    else
        echo -e "${YELLOW}⚠️  api/keys.txt 存在但没有有效的key${NC}"
    fi
elif [ -f "$ENV_FILE" ]; then
    # Export variables so Python subprocess can access them
    set -a  # automatically export all variables
    source "$ENV_FILE"
    set +a  # disable auto-export
    # Count keys from .env
    KEY_COUNT=$(grep -E '^DASHSCOPE_API_KEY_[0-9]+=' "$ENV_FILE" | wc -l | tr -d ' ')
    if [ "$KEY_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✅ API Keys 已配置: $KEY_COUNT 个 (from .env)${NC}"
    elif [ -n "$DASHSCOPE_API_KEY" ]; then
        echo -e "${GREEN}✅ API Key 已配置 (single key from .env)${NC}"
    fi
elif [ -n "$DASHSCOPE_API_KEY" ]; then
    echo -e "${GREEN}✅ API Key 已配置 (from environment)${NC}"
else
    echo -e "${RED}错误: 未找到 API Key 配置${NC}"
    echo "请选择以下方式之一配置:"
    echo "  1. 创建 api/keys.txt (每行一个key)"
    echo "  2. 创建 .env 文件 (DASHSCOPE_API_KEY_1=xxx)"
    echo "  3. 设置环境变量: export DASHSCOPE_API_KEY='your-key'"
    exit 1
fi
echo "输入目录: $INPUT_DIR"
echo "输出目录: $OUTPUT_DIR"
echo "并发数: $SEMAPHORE"

# 检查断点续传状态
if [ -f "$PROGRESS_FILE" ]; then
    echo ""
    echo -e "${BLUE}📌 检测到进度文件，启用断点续传${NC}"
    python3 "$SCRIPTS_DIR/progress_manager.py" --status --progress-file "$PROGRESS_FILE" 2>/dev/null || true
    echo ""
    RESUME_FLAG=""
else
    echo ""
    echo "📝 首次运行，创建新进度"
    RESUME_FLAG=""
fi

echo ""

# 创建目录
mkdir -p "$INPUT_DIR" "$OUTPUT_DIR" "$SPLIT_DIR" "$LOGS_DIR"

# 检查输入PDF
PDF_COUNT=$(find "$INPUT_DIR" -maxdepth 1 -name "*.pdf" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$PDF_COUNT" -eq 0 ]; then
    echo "请将PDF文件放入 input/ 目录"
    exit 0
fi

echo "找到 $PDF_COUNT 个PDF文件"
echo ""

START_TIME=$(date +%s)
echo "开始时间: $(date)"
echo ""

# 启动后台监控 (如果启用)
MONITOR_PID=""
if [ "$MONITOR" = true ]; then
    echo -e "${BLUE}📊 启动后台监控...${NC}"
    mkdir -p "$SCRIPT_DIR/monitor" "$SCRIPT_DIR/history"
    python3 "$ADMIN_DIR/monitor_daemon.py" \
        --task-name "$TASK_NAME" \
        --base-dir "$SCRIPT_DIR" \
        --interval 30 &
    MONITOR_PID=$!
    echo "   监控进程 PID: $MONITOR_PID"
    echo "   日志目录: $SCRIPT_DIR/monitor/"
    echo ""
fi

# 注册退出时停止监控
cleanup() {
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        echo ""
        echo "停止监控进程..."
        kill "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Step 1: 智能分割大PDF
echo "======================================================================"
echo "Step 1: 智能分割大PDF (>$MAX_PAGES_PER_CHUNK 页或 >$MAX_SIZE_MB MB)"
echo "======================================================================"

python3 "$SCRIPTS_DIR/split_large_pdfs_smart.py" \
    --input-dir "$INPUT_DIR" \
    --output-dir "$SPLIT_DIR" \
    --chunk-size "$MAX_PAGES_PER_CHUNK" \
    --max-chunk-size-mb "$MAX_SIZE_MB" \
    --mapping-file "$SPLIT_DIR/split_mapping.json"

echo ""

# Step 2: 处理分块PDF (使用目录模式)
echo "======================================================================"
echo "Step 2: 处理分块PDF"
echo "======================================================================"

CHUNK_COUNT=$(find "$SPLIT_DIR" -maxdepth 1 -name "*.pdf" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$CHUNK_COUNT" -gt 0 ]; then
    echo "处理 $CHUNK_COUNT 个分块PDF..."

    # Process with Max Safe concurrency
    PYTHONUNBUFFERED=1 python3 "$SCRIPTS_DIR/docmind_converter.py" \
        --input "$SPLIT_DIR" \
        --output "$OUTPUT_DIR/chunks" \
        --semaphore-limit "$LLM_CONCURRENT" \
        --pdf-concurrency "$SEMAPHORE" \
        --progress-file "$PROGRESS_FILE" \
        2>&1 | tee "$LOGS_DIR/chunks_processing.log"
else
    echo "没有需要处理的分块PDF"
fi

echo ""

# Step 2.5: 重试失败的页面
echo "======================================================================"
echo "Step 2.5: 重试失败的页面"
echo "======================================================================"

if [ -d "$OUTPUT_DIR/chunks" ]; then
    # Check if there are any failed pages to retry
    FAILED_COUNT=$(find "$OUTPUT_DIR/chunks" -name "*.validation.yaml" -exec grep -l "failed_pages_detail:" {} \; 2>/dev/null | wc -l | tr -d ' ')

    if [ "$FAILED_COUNT" -gt 0 ]; then
        echo "发现 $FAILED_COUNT 个chunk有失败页面，开始重试..."

        python3 "$SCRIPTS_DIR/retry_failed_pages.py" \
            --chunks-dir "$OUTPUT_DIR/chunks" \
            --api-keys "$SCRIPT_DIR/api/keys.txt" \
            --output "$OUTPUT_DIR/chunks/retry_failures.yaml" \
            2>&1 | tee "$LOGS_DIR/retry_failed.log"
    else
        echo "没有需要重试的失败页面"
    fi
else
    echo "没有chunk输出目录，跳过重试步骤"
fi

echo ""

# Step 3: 处理小PDF（不需要分割的）
echo "======================================================================"
echo "Step 3: 处理小PDF"
echo "======================================================================"

# 读取mapping，找出不需要分割的PDF，创建临时目录
if [ -f "$SPLIT_DIR/split_mapping.json" ]; then
    DIRECT_COUNT=$(python3 -c "
import json
with open('$SPLIT_DIR/split_mapping.json') as f:
    data = json.load(f)
print(len(data.get('direct', [])))
" 2>/dev/null)

    if [ "$DIRECT_COUNT" -gt 0 ]; then
        echo "处理 $DIRECT_COUNT 个小PDF..."

        # 创建临时目录存放小PDF的符号链接
        DIRECT_DIR="$SCRIPT_DIR/input/direct_pdfs"
        mkdir -p "$DIRECT_DIR"
        rm -f "$DIRECT_DIR"/*.pdf 2>/dev/null || true

        # 创建符号链接
        python3 -c "
import json
import os
from pathlib import Path

with open('$SPLIT_DIR/split_mapping.json') as f:
    data = json.load(f)

direct_dir = Path('$DIRECT_DIR')
for item in data.get('direct', []):
    pdf_path = Path(item['pdf_path'])
    if pdf_path.exists():
        link_path = direct_dir / pdf_path.name
        if link_path.exists():
            link_path.unlink()
        os.symlink(pdf_path, link_path)
        print(f'Linked: {pdf_path.name}')
"

        # Process with Max Safe concurrency
        PYTHONUNBUFFERED=1 python3 "$SCRIPTS_DIR/docmind_converter.py" \
            --input "$DIRECT_DIR" \
            --output "$OUTPUT_DIR" \
            --semaphore-limit "$LLM_CONCURRENT" \
            --pdf-concurrency "$SEMAPHORE" \
            --progress-file "$PROGRESS_FILE" \
            2>&1 | tee "$LOGS_DIR/direct_processing.log"
    else
        echo "没有需要直接处理的小PDF"
    fi
fi

echo ""

# Step 4: 合并分块结果
echo "======================================================================"
echo "Step 4: 合并分块结果"
echo "======================================================================"

if [ -f "$SPLIT_DIR/split_mapping.json" ] && [ -d "$OUTPUT_DIR/chunks" ]; then
    python3 "$SCRIPTS_DIR/merge_results_full.py" \
        --mapping-file "$SPLIT_DIR/split_mapping.json" \
        --results-dir "$OUTPUT_DIR/chunks" \
        --output-dir "$OUTPUT_DIR"
fi

# 更新进度状态为完成
if [ -f "$PROGRESS_FILE" ]; then
    python3 -c "
import json
from datetime import datetime

with open('$PROGRESS_FILE', 'r') as f:
    data = json.load(f)

data['status'] = 'completed'
data['completed_at'] = datetime.now().isoformat()
data['steps']['merge'] = {'status': 'completed', 'completed_at': datetime.now().isoformat()}

with open('$PROGRESS_FILE', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
" 2>/dev/null || true
fi

# Step 5: Create final-delivery folder (flat structure: no subfolders)
echo "======================================================================"
echo "Step 5: Create final-delivery folder"
echo "======================================================================"

mkdir -p "$FINAL_DELIVERY"

# Find all processed PDFs and copy .md + .yaml to final-delivery (flat, no subfolders)
for pdf_dir in "$OUTPUT_DIR"/*/; do
    # Skip chunks directory
    if [[ "$(basename "$pdf_dir")" == "chunks" ]]; then
        continue
    fi

    # Get short name from directory
    dir_name=$(basename "$pdf_dir")
    # Create clean filename (first 50 chars, sanitized)
    short_name=$(echo "$dir_name" | cut -c1-50 | sed 's/ /-/g' | sed 's/[^a-zA-Z0-9-]//g')

    if [ -n "$short_name" ]; then
        # Copy .md file directly to final-delivery (no subfolder)
        md_file=$(find "$pdf_dir" -maxdepth 1 -name "*.md" -type f | head -1)
        if [ -n "$md_file" ]; then
            cp "$md_file" "$FINAL_DELIVERY/$short_name.md"
            echo "  ✅ $short_name.md"
        fi

        # Copy YAML file directly to final-delivery (no subfolder)
        yaml_file=$(find "$pdf_dir" -maxdepth 1 -name "*_all_figures.yaml" -type f | head -1)
        if [ -z "$yaml_file" ]; then
            # For merged PDFs, YAML file has same name as directory
            yaml_file=$(find "$pdf_dir" -maxdepth 1 -name "*.yaml" -type f ! -name "*.validation.yaml" | head -1)
        fi
        if [ -n "$yaml_file" ]; then
            cp "$yaml_file" "$FINAL_DELIVERY/$short_name.yaml"
            echo "  ✅ $short_name.yaml"
        fi
    fi
done

echo ""
echo "Final delivery: $FINAL_DELIVERY"
echo ""

# Step 6: Markdown Post-processing
echo "======================================================================"
echo "Step 6: Markdown Post-processing"
echo "======================================================================"

python3 "$SCRIPTS_DIR/postprocess.py" \
    --input "$FINAL_DELIVERY" \
    --fix-tables \
    --fix-headings \
    --merge-empty-lines \
    --validate-latex

echo ""

# Step 7: Generate Quality Report
echo "======================================================================"
echo "Step 7: Generate Quality Report"
echo "======================================================================"

python3 "$SCRIPTS_DIR/generate_quality_report.py" \
    --input "$FINAL_DELIVERY" \
    --progress "$PROGRESS_FILE" \
    --json

echo ""

# Step 8: Final Delivery Validation
echo "======================================================================"
echo "Step 8: Final Delivery Validation"
echo "======================================================================"

# Count expected folders from mapping
if [ -f "$SPLIT_DIR/split_mapping.json" ]; then
    EXPECTED_COUNT=$(python3 -c "
import json
with open('$SPLIT_DIR/split_mapping.json') as f:
    data = json.load(f)
# Count unique original PDFs
chunks = data.get('chunks', [])
direct = data.get('direct', [])
original_pdfs = set(c['original_pdf'] for c in chunks)
original_pdfs.update(d['pdf_path'].split('/')[-1] for d in direct)
print(len(original_pdfs))
" 2>/dev/null)

    python3 "$SCRIPTS_DIR/final_delivery_check.py" \
        --delivery-dir "$FINAL_DELIVERY" \
        --expected-count "$EXPECTED_COUNT" \
        --output-report "$FINAL_DELIVERY/VALIDATION_REPORT.json"
else
    python3 "$SCRIPTS_DIR/final_delivery_check.py" \
        --delivery-dir "$FINAL_DELIVERY" \
        --output-report "$FINAL_DELIVERY/VALIDATION_REPORT.json"
fi

echo ""

# 统计结果
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

echo ""
echo "======================================================================"
echo -e "${GREEN}✅ 处理完成!${NC}"
echo "======================================================================"
echo "总耗时: ${MINUTES}分${SECONDS}秒"
echo "结束时间: $(date)"
echo ""

echo "结果统计:"
YAML_COUNT=$(find "$OUTPUT_DIR" -name "*.yaml" 2>/dev/null | wc -l | tr -d ' ')
MD_COUNT=$(find "$OUTPUT_DIR" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
JSON_COUNT=$(find "$OUTPUT_DIR" -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
IMG_COUNT=$(find "$OUTPUT_DIR" -name "*.png" 2>/dev/null | wc -l | tr -d ' ')

echo "  • YAML 文件: $YAML_COUNT"
echo "  • Markdown 文件: $MD_COUNT"
echo "  • JSON 文件: $JSON_COUNT"
echo "  • 图片文件: $IMG_COUNT"
echo ""
echo "输出目录: $OUTPUT_DIR"
echo "进度文件: $PROGRESS_FILE"
# Step 9: Generate Task Report (可选，失败不影响主流程)
echo "======================================================================"
echo "Step 9: Generate Task Report"
echo "======================================================================"

python3 "$ADMIN_DIR/generate_report.py" \
    --task-name "$TASK_NAME" \
    --base-dir "$SCRIPT_DIR" || echo -e "${YELLOW}⚠️  报告生成失败，但不影响转换结果${NC}"

echo ""
echo "提示: 使用 ./run.sh --status 查看详细进度"
echo "报告目录: $SCRIPT_DIR/reports/$TASK_NAME/"
