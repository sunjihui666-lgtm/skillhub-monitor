#!/bin/bash
# macOS 双击启动：把本文件拖到 Dock 或在访达里双击即可
cd "$(dirname "$0")"
chmod +x ./start.sh 2>/dev/null
exec ./start.sh "$@"
