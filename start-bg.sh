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
  # 如果用户手动指定就用它
  if [[ -n "$PKG_MGR" ]]; then
    echo "$PKG_MGR"; return 0
  fi
  # 否则按优先级探测
  for pm in pnpm yarn npm bun; do
    if command -v "$pm" >/dev/null 2>&1; then
      echo "$pm"; return 0
    fi
  done
  echo "npm"
}

start_backend() {
  cd "$ROOT"   # ← 改这里：到项目根，而不是 server/
  local pidf="$LOG_DIR/backend.pid"
  if running "$pidf"; then
    echo "[INFO] 后端已在运行中 (PID $(cat "$pidf"))，跳过启动。"
    return 0
  fi
  echo "[INFO] 启动后端：uvicorn --app-dir \"$SERVER_DIR\" app.main:app --host $BACKEND_HOST --port $BACKEND_PORT --reload"
  nohup uvicorn --app-dir "$SERVER_DIR" app.main:app \
      --host "$BACKEND_HOST" \
      --port "$BACKEND_PORT" \
      --reload \
      >"$LOG_DIR/backend.log" 2>&1 &
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

  echo "[INFO] 启动前端：$pm run dev（后台）"
  # 统一通过环境变量传入端口（Vite/CRA 等都支持 PORT）
  PORT="$FRONTEND_PORT" nohup "$pm" run dev >"$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$pidf"
  echo "[OK] 前端 PID $(cat "$pidf")，日志：$LOG_DIR/frontend.log"
}

# === 执行 ===
start_backend
start_frontend

echo "[INFO] 已在后台启动完成。"
echo "       后端：http://$BACKEND_HOST:$BACKEND_PORT"
echo "       前端：http://localhost:$FRONTEND_PORT"
echo "       查看日志：tail -f $LOG_DIR/backend.log  或  tail -f $LOG_DIR/frontend.log"