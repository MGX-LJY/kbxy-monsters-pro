#!/usr/bin/env bash
set -euo pipefail

# === 可改环境变量（也可运行时临时传） ===
ROOT_DEFAULT="/Users/martinezdavid/Documents/MG/code/kbxy-monsters-pro"
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
             --reload-dir server --reload-dir rules
             --reload-exclude '.venv/*'
             --reload-exclude '*/site-packages/*'
             --reload-exclude '**/__pycache__/*')

  if [[ -f "$env_file" ]]; then
    cmd+=(--env-file "$env_file")
    echo "[INFO] 使用环境文件：$env_file"
  else
    echo "[WARN] 未找到环境文件：$env_file（将仅使用当前环境变量 APP_ENV=${APP_ENV:-dev}）"
  fi

  echo "[INFO] 启动后端（${APP_ENV:-dev}）：${cmd[*]}"
  # 用 env 注入，给默认值，避免 set -u 因空变量报错
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
choose_env
start_backend
start_frontend

echo
echo "[INFO] 已在后台启动完成。"
echo "       环境：${APP_ENV:-dev}"
echo "       后端：http://$BACKEND_HOST:$BACKEND_PORT"
echo "       前端：http://localhost:$FRONTEND_PORT"
echo "       查看日志：tail -f $LOG_DIR/backend.log  或  tail -f $LOG_DIR/frontend.log"