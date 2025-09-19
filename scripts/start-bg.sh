#!/usr/bin/env bash
set -euo pipefail

# === 自动检测项目根目录 ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(dirname "$SCRIPT_DIR")"
ROOT="${ROOT:-$ROOT_DEFAULT}"

VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
SERVER_DIR="${SERVER_DIR:-$ROOT/server}"
CLIENT_DIR="${CLIENT_DIR:-$ROOT/client}"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

LOG_DIR="${LOG_DIR:-$ROOT/.logs}"
PKG_MGR="${PKG_MGR:-}"   # 可指定：pnpm / yarn / npm / bun


mkdir -p "$LOG_DIR"

echo "[INFO] 项目根目录：$ROOT"

# === 选 Python 解释器 ===
PYTHON_BIN="python"
if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
fi

# === 激活虚拟环境（如果存在） ===
if [[ -f "$VENV_DIR/bin/activate" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
  echo "[INFO] 已激活虚拟环境：$VENV_DIR"
else
  echo "[WARN] 未发现虚拟环境（$VENV_DIR），跳过激活。"
fi

# === 小工具函数 ===
running() {
  local pidfile="$1"
  [[ -f "$pidfile" ]] && ps -p "$(cat "$pidfile")" >/dev/null 2>&1
}

pick_pm() {
  if [[ -n "$PKG_MGR" ]]; then
    echo "$PKG_MGR"; return 0
  fi
  for pm in pnpm yarn npm bun; do
    if command -v "$pm" >/dev/null 2>&1; then
      echo "$pm"; return 0
    fi
  done
  echo "npm"
}

choose_env() {
  # 检查命令行参数
  if [[ "${1:-}" == "dev" ]] || [[ "${1:-}" == "test" ]]; then
    APP_ENV="$1"
    export APP_ENV
    echo "[INFO] 使用命令行指定环境：$APP_ENV"
    return 0
  fi
  
  # 检查环境变量
  if [[ -n "${APP_ENV:-}" ]]; then
    echo "[INFO] 使用环境变量 APP_ENV=$APP_ENV"
    return 0
  fi
  
  # 交互式选择
  echo
  echo "请选择启动环境："
  echo "  [1] dev  （开发环境）"
  echo "  [2] test （测试环境）"
  read -rp "请输入数字 (1/2): " choice
  case "${choice:-}" in
    1) APP_ENV="dev" ;;
    2) APP_ENV="test" ;;
    *) echo "[ERR] 无效选择：$choice"; exit 1 ;;
  esac
  export APP_ENV
  echo "[INFO] 已选择环境：${APP_ENV:-dev}"
}

load_env_file() {
  # 将 .env.<env> 中的变量导入当前 shell（便于本脚本判断 DATABASE_URL 等）
  local env_file="$ROOT/.env.${APP_ENV:-dev}"
  if [[ -f "$env_file" ]]; then
    # shellcheck disable=SC1090,SC2046
    set -a
    source "$env_file"
    set +a
    echo "[INFO] 已加载环境文件到当前会话：$env_file"
  else
    echo "[WARN] 未找到环境文件：$env_file（将仅使用当前环境变量 APP_ENV=${APP_ENV:-dev}）"
  fi
}


start_backend() {
  cd "$ROOT"
  local pidf="$LOG_DIR/backend.pid"
  if running "$pidf"; then
    echo "[INFO] 后端已在运行中 (PID $(cat "$pidf"))，跳过启动。"
    return 0
  fi

  local env_file="$ROOT/.env.${APP_ENV:-dev}"
  local cmd=(uvicorn --app-dir "$SERVER_DIR" app.main:app
             --host "$BACKEND_HOST" --port "$BACKEND_PORT"
             --reload
             --reload-exclude '.venv/*'
             --reload-exclude '*/site-packages/*'
             --reload-exclude '**/__pycache__/*')

  if [[ -f "$env_file" ]]; then
    cmd+=(--env-file "$env_file")
    echo "[INFO] 使用环境文件：$env_file"
  fi

  echo "[INFO] 启动后端（${APP_ENV:-dev}）：${cmd[*]}"
  echo "[INFO] 备份调度器将自动启动..."
  nohup env APP_ENV="${APP_ENV:-dev}" "${cmd[@]}" >"$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$pidf"
  echo "[OK] 后端 PID $(cat "$pidf")，日志：$LOG_DIR/backend.log"
  
}

start_frontend() {
  cd "$CLIENT_DIR"
  if [[ ! -f package.json ]]; then
    echo "[WARN] 未找到 $CLIENT_DIR/package.json，跳过前端启动。"
    return 0
  fi

  local pm
  pm="$(pick_pm)"
  local pidf="$LOG_DIR/frontend.pid"

  if running "$pidf"; then
    echo "[INFO] 前端已在运行中 (PID $(cat "$pidf"))，跳过启动。"
    return 0
  fi

  echo "[INFO] 启动前端（${APP_ENV:-dev}）：$pm run dev（后台）"
  nohup env PORT="${FRONTEND_PORT:-5173}" APP_ENV="${APP_ENV:-dev}" "$pm" run dev >"$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$pidf"
  echo "[OK] 前端 PID $(cat "$pidf")，日志：$LOG_DIR/frontend.log"
}

# === 执行 ===
choose_env "${1:-}"
load_env_file
start_backend
start_frontend

echo
echo "[INFO] 已在后台启动完成。"
echo "       环境：${APP_ENV:-dev}"
echo "       后端：http://$BACKEND_HOST:$BACKEND_PORT"
echo "       前端：http://localhost:$FRONTEND_PORT"
echo "       健康检查：http://$BACKEND_HOST:$BACKEND_PORT/health"
echo "       备份管理：http://localhost:$FRONTEND_PORT/backup"
echo
echo "       查看日志："
echo "         tail -f $LOG_DIR/backend.log"
echo "         tail -f $LOG_DIR/frontend.log"
echo
echo "       停止服务："
echo "         $ROOT/scripts/stop-bg.sh"
echo "         或 make stop"