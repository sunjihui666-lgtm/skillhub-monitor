#!/bin/bash
# ============================================================
#  Skill 下载量看板 · 一键启动
#  自动：准备 Python 环境 -> 安装依赖 -> 启动本地服务 -> 打开浏览器
#  监控对象读config.json（代码内不写死 slug），在页面点「⚙ 监控对象」即可改
#  用法：./start.sh            默认端口 8787
#        ./start.sh --port 9000
# ============================================================
set -e

# 切到脚本所在目录（双击运行时 cwd 可能是用户根目录）
cd "$(dirname "$0")"
ROOT="$(pwd)"

HOST="127.0.0.1"
PORT="8787"

# 解析 --port / --host
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    *) shift ;;
  esac
done

URL="http://${HOST}:${PORT}/"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

say() { printf "\033[36m[看板]\033[0m %s\n" "$1"; }
err() { printf "\033[31m[看板]\033[0m %s\n" "$1"; }

# ---------- 1. 找 Python ----------
find_python() {
  for c in python3 python \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
        echo "$c"; return 0
      fi
    fi
  done
  return 1
}

PYBASE="$(find_python || true)"
if [ -z "$PYBASE" ]; then
  err "未找到 Python 3.8+，请先安装 Python 3（https://www.python.org/downloads/）"
  echo; read -n 1 -s -r -p "按任意键退出…"; exit 1
fi

# ---------- 2. 准备虚拟环境 ----------
if [ ! -x "$PY" ]; then
  say "首次运行，创建虚拟环境…"
  "$PYBASE" -m venv "$VENV" >/dev/null 2>&1 || {
    err "创建虚拟环境失败。"; read -n 1 -s -r -p "按任意键退出…"; exit 1; }
fi

# ---------- 3. 安装依赖 ----------
if ! "$PY" -c 'import requests' >/dev/null 2>&1; then
  say "安装依赖 requests（首次约 10 秒）…"
  "$PY" -m pip install -q --disable-pip-version-check requests || {
    err "依赖安装失败，请检查网络后重试。"; read -n 1 -s -r -p "按任意键退出…"; exit 1; }
fi

# ---------- 4. 端口占用检查 ----------
if "$PY" - "$HOST" "$PORT" <<'EOF' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(0.4)
sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)
EOF
then
  say "端口 $PORT 已被占用，直接打开页面：$URL"
  ( sleep 0.5; command -v open >/dev/null && open "$URL" || true )
  exit 0
fi

# ---------- 5. 启动服务 + 打开浏览器 ----------
say "启动本地服务：$URL"
( sleep 1.2
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi
) &

exec "$PY" serve.py --host "$HOST" --port "$PORT"
