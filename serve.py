#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地看板服务：静态托管 dashboard.html + 反向代理 SkillHub API（解决浏览器 CORS）

用法：
  python serve.py              # 默认 127.0.0.1:8787
  python serve.py --port 9000

启动后打开：
  http://127.0.0.1:8787/

页面里的「代理地址」默认填 http://127.0.0.1:8787/api ，与本站同源，浏览器直连不再被 CORS 拦截。

说明：
  - 只代理 GET/POST 到 https://api.skillhub.cn/api/ 下的路径，其他一律 404；
  - 显式禁用系统代理环境变量，避免走代理导致失败。
  - 监控清单不在代码里：读 config.json，页面可回写。
"""

import argparse
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import os
import sys

UPSTREAM = "https://api.skillhub.cn"
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "config.json")

# 禁用环境变量里的代理（很多环境会设置 http_proxy 导致请求失败）
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        print("[serve]", fmt % args)

    # ---------- 配置回写 ----------
    def _save_config(self):
        """接收页面保存的 config.json 内容并落回文件"""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return self._json(400, {"error": "empty body"})
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self._json(400, {"error": f"invalid json: {e}"})

        # 基本结构校验：groups 必须在，且每组必须有 skills 数组
        groups = data.get("groups")
        if not isinstance(groups, list) or not groups:
            return self._json(400, {"error": "config.groups 必须是非空数组"})
        for i, g in enumerate(groups):
            if not isinstance(g.get("skills"), list):
                return self._json(400, {"error": f"groups[{i}].skills 必须是数组"})

        # 先写临时文件再替换，避免写坏原文件
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
        print(f"[serve] config.json 已更新（{sum(len(g['skills']) for g in groups)} 个 skill）")
        return self._json(200, {"ok": True, "path": CONFIG_FILE})

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    # ---------- 代理 ----------
    def _proxy(self, method):
        # 路径形如 /api/v1/skills/batch  ->  上游 /api/v1/skills/batch
        path = self.path
        if not path.startswith("/api/"):
            self.send_error(404, "not found")
            return

        url = UPSTREAM + path
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "skillhub-monitor/1.0")

        try:
            with opener.open(req, timeout=30) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                # 同源，无需 CORS 头；但补上更保险
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            msg = json.dumps({"error": str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy("GET")
        if self.path in ("/", ""):
            self.path = "/dashboard.html"
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api-config":
            return self._save_config()
        if self.path.startswith("/api/"):
            return self._proxy("POST")
        self.send_error(405)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    ap = argparse.ArgumentParser(description="SkillHub 看板本地服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    # 打印当前配置的组，供确认监控对象
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        groups = cfg.get("groups") or []
        print(f"[serve] config.json 载入 {len(groups)} 个组：")
        for g in groups:
            mark = " (默认)" if g.get("enabled") else ""
            print(f"           - {g.get('name', '(未命名)')}{mark}：{len(g.get('skills') or [])} 个 skill")
    except Exception as e:
        print(f"[serve] 警告：读不到 config.json（{e}），看板将用内嵌快照")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.host, args.port), Handler) as httpd:
        print("=" * 60)
        print("SkillHub 看板已启动")
        print(f"  打开：{args.host}:{args.port}")
        print(f"  代理：{args.host}:{args.port}/api/v1/...  ->  {UPSTREAM}/api/v1/...")
        print(f"  配置：config.json（可在页面里改并点保存）")
        print("  Ctrl+C 退出")
        print("=" * 60)
        sys.stdout.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已退出。")


if __name__ == "__main__":
    main()
