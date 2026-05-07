#!/bin/bash
# DocMind 0.8 — thin entry-point.
#
# Pipeline orchestration lives in ``conversao/orchestrator.py`` (Fase G of
# PLANO_REFATORACAO.md). Bash retains three jobs only:
#   1. API key loading (api/keys.txt → DASHSCOPE_API_KEY_N).
#   2. Monitor daemon spawn/cleanup via ``trap`` (bash-idiomatic).
#   3. ``--history`` shortcut (admin script, not part of the pipeline).
#
# Everything else (Steps 1–9, --status, --restart, --retry-failed) delegates
# to ``python orchestrator.py``. CLI surface preserved for operators.

set -e

# Colors (used for env-loading messages and monitor daemon)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADMIN_DIR="$SCRIPT_DIR/scripts/admin"
ORCHESTRATOR="$SCRIPT_DIR/orchestrator.py"

echo "======================================================================"
echo "DocMind 0.8 - PDF to Markdown 转换系统"
echo "======================================================================"

# --- arg parsing -----------------------------------------------------------

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
            cat <<'EOF'

用法: ./run.sh [选项]

选项:
  --restart         强制从头开始 (自动归档旧进度)
  --status          仅显示当前进度状态
  --retry-failed    仅重试之前失败的页面
  --task-name, -t   设置任务名称 (用于监控和归档)
  --monitor, -m     启用后台资源监控
  --history         列出历史任务记录
  --help, -h        显示此帮助信息

环境变量:
  MAX_PAGES         每块最大页数 (默认: 50)
  MAX_SIZE          每块最大大小MB (默认: 50)
  SEMAPHORE         PDF并发数 (默认: 30, 优化为6 keys)
  LLM_CONCURRENT    每PDF的LLM并发数 (默认: 10, 优化为6 keys)

示例:
  ./run.sh --task-name lenin_21-30 --monitor    # 带监控的新任务
  ./run.sh --restart --task-name batch2         # 重新开始新任务
  ./run.sh --history                            # 查看历史记录

EOF
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

# --- short-circuits (no API key, no env required) ------------------------

if [ "$LIST_HISTORY" = true ]; then
    python3 "$ADMIN_DIR/archive_progress.py" --list
    exit 0
fi

if [ "$STATUS_ONLY" = true ]; then
    python3 "$ORCHESTRATOR" status
    exit 0
fi

# --- auto-generate task name ---------------------------------------------

if [ -z "$TASK_NAME" ]; then
    TASK_NAME="task_$(date +%Y%m%d_%H%M%S)"
fi
echo "任务名称: $TASK_NAME"

# --- API Key configuration -----------------------------------------------
# Priority: 1) api/keys.txt  2) .env file  3) environment variable

API_KEYS_FILE="$SCRIPT_DIR/api/keys.txt"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$API_KEYS_FILE" ]; then
    KEY_COUNT=$(grep -v '^#' "$API_KEYS_FILE" | grep -v '^$' | wc -l | tr -d ' ')
    if [ "$KEY_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✅ API Keys 已配置: $KEY_COUNT 个 (from api/keys.txt)${NC}"
        KEY_INDEX=1
        while IFS= read -r KEY || [ -n "$KEY" ]; do
            if [ -n "$KEY" ] && [[ ! "$KEY" =~ ^# ]]; then
                export "DASHSCOPE_API_KEY_$KEY_INDEX=$KEY"
                KEY_INDEX=$((KEY_INDEX + 1))
            fi
        done < "$API_KEYS_FILE"
    else
        echo -e "${YELLOW}⚠️  api/keys.txt 存在但没有有效的key${NC}"
    fi
elif [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
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

# --- monitor daemon (optional) -------------------------------------------

MONITOR_PID=""
cleanup() {
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        echo "停止监控进程..."
        kill "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

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
fi

# --- delegate to orchestrator --------------------------------------------

ORCHESTRATOR_ARGS=("run" "--task-name" "$TASK_NAME")
if [ "$RESTART" = true ]; then
    ORCHESTRATOR_ARGS+=("--restart")
fi
if [ "$RETRY_FAILED" = true ]; then
    ORCHESTRATOR_ARGS+=("--retry-failed")
fi

# Disable set -e so the orchestrator's exit code propagates verbatim.
set +e
python3 "$ORCHESTRATOR" "${ORCHESTRATOR_ARGS[@]}"
exit $?
