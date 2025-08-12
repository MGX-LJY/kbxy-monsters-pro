#!/usr/bin/env bash
set -euo pipefail

ROOT_DEFAULT="/Users/martinezdavid/Documents/MG/code/kbxy-monsters-pro"
ROOT="${ROOT:-$ROOT_DEFAULT}"
LOG_DIR="${LOG_DIR:-$ROOT/.logs}"

stop_one() {
  local name="$1"
  local pidf="$LOG_DIR/$name.pid"
  if [[ -f "$pidf" ]]; then
    local pid
    pid="$(cat "$pidf" || true)"
    if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
      echo "[INFO] 结束 $name (PID $pid)…"
      kill "$pid" || true
      # 等待最多 5s，仍在则强杀
      for _ in {1..10}; do
        if ps -p "$pid" >/dev/null 2>&1; then
          sleep 0.5
        else
          break
        fi
      done
      if ps -p "$pid" >/dev/null 2>&1; then
        echo "[WARN] 进程未退出，尝试强制结束 $pid"
        kill -9 "$pid" || true
      fi
    else
      echo "[INFO] 未检测到运行中的 $name。"
    fi
    rm -f "$pidf"
  else
    echo "[INFO] 未找到 $name 的 pid 文件：$pidf"
  fi
}

stop_one "backend"
stop_one "frontend"

echo "[OK] 已停止后台进程。"