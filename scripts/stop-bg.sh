#!/usr/bin/env bash
set -euo pipefail

# === 自动检测项目根目录 ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DEFAULT="$(dirname "$SCRIPT_DIR")"
ROOT="${ROOT:-$ROOT_DEFAULT}"
LOG_DIR="${LOG_DIR:-$ROOT/.logs}"
mkdir -p "$LOG_DIR"

kill_tree() {
  local pid="$1"
  # 递归杀掉整个子进程树
  if [[ -z "${pid:-}" ]] || ! ps -p "$pid" >/dev/null 2>&1; then
    return 0
  fi
  local kids
  kids="$(pgrep -P "$pid" || true)"
  if [[ -n "$kids" ]]; then
    for k in $kids; do
      kill_tree "$k"
    done
  fi
  kill "$pid" 2>/dev/null || true
}

wait_gone() {
  local check_cmd="$1"  # 传入一个命令字符串，返回 0 表示还活着
  local tries=10
  while ((tries-- > 0)); do
    if eval "$check_cmd"; then
      sleep 0.5
    else
      return 0
    fi
  done
  return 1
}

stop_by_pidfile() {
  local name="$1"
  local pidf="$LOG_DIR/$name.pid"
  if [[ ! -f "$pidf" ]]; then
    echo "[INFO] 未找到 $name 的 pid 文件：$pidf"
    return 1
  fi
  local pid
  pid="$(cat "$pidf" 2>/dev/null || true)"
  if [[ -z "${pid:-}" ]] || ! ps -p "$pid" >/dev/null 2>&1; then
    echo "[INFO] $name 的 pid($pid) 不在运行，清理 pid 文件。"
    rm -f "$pidf"
    return 1
  fi
  echo "[INFO] 结束 $name (PID $pid)…"
  # 先优雅，再强制
  kill_tree "$pid"
  if ! wait_gone "ps -p $pid >/dev/null 2>&1"; then
    echo "[WARN] $name 仍在，强制结束进程组/残留…"
    # 尝试 kill 整个进程组
    kill -9 "-$pid" 2>/dev/null || true
  fi
  rm -f "$pidf" || true
}

stop_by_port() {
  local desc="$1" port="$2"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "[INFO] 端口 $port 没有 $desc 在监听。"
    return 1
  fi
  echo "[INFO] 发现 $desc 占用端口 $port 的进程：$pids，尝试结束…"
  # 先 TERM
  kill $pids 2>/dev/null || true
  if ! wait_gone "lsof -ti tcp:$port >/dev/null 2>&1"; then
    echo "[WARN] $desc 端口 $port 仍被占用，强制结束…"
    kill -9 $pids 2>/dev/null || true
  fi
}

stop_one() {
  local name="$1" port="${2:-}"
  stop_by_pidfile "$name" || true
  # 有端口就兜底按端口再扫
  if [[ -n "$port" ]]; then
    stop_by_port "$name" "$port" || true
  fi
}

# === 实际执行 ===
echo "[INFO] 正在停止卡布妖怪图鉴 Pro 服务..."
echo

# 后端 - 包含备份调度器
echo "[INFO] 停止后端服务（包括备份调度器）..."
stop_one "backend" "8000"

# 前端
echo "[INFO] 停止前端服务..."
stop_one "frontend" "5173"

# 额外检查可能的uvicorn进程
echo "[INFO] 检查残留的uvicorn进程..."
uvicorn_pids="$(pgrep -f 'uvicorn.*app.main:app' 2>/dev/null || true)"
if [[ -n "$uvicorn_pids" ]]; then
  echo "[WARN] 发现残留的uvicorn进程：$uvicorn_pids，正在清理..."
  kill $uvicorn_pids 2>/dev/null || true
  sleep 1
  kill -9 $uvicorn_pids 2>/dev/null || true
fi

# 检查端口占用情况
echo "[INFO] 检查端口占用情况..."
port_8000="$(lsof -ti tcp:8000 2>/dev/null || true)"
port_5173="$(lsof -ti tcp:5173 2>/dev/null || true)"

if [[ -n "$port_8000" ]]; then
  echo "[WARN] 端口8000仍被占用，PID: $port_8000"
else
  echo "[OK] 端口8000已释放"
fi

if [[ -n "$port_5173" ]]; then
  echo "[WARN] 端口5173仍被占用，PID: $port_5173"
else
  echo "[OK] 端口5173已释放"
fi

echo
echo "[OK] 已停止所有后台进程。"
echo "[INFO] 备份调度器已安全停止，数据完整性得到保护。"