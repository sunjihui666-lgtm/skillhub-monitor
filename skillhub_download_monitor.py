#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SkillHub 下载量监控 / 增长量统计（配置驱动）

监控对象来自同目录 **config.json**，改配置即可切换，代码里不写死任何 slug。

配置格式（config.json）：
  {
    "settings": { "interval": 60, "rounds": 5, "unit": "min" },
    "groups": [
      { "name": "组名", "enabled": true,
        "skills": [ { "slug": "@org-xxx/yyy", "name": "显示名", "enabled": true } ] }
    ]
  }

原理：
  SkillHub 没有公开的历史趋势接口，/api/v1/skills/batch 只返回**累计下载量**。
  因此增长量必须通过**定时采样 + 相邻两次差分**得到：
      每分钟增长 = (本次 downloads - 上次 downloads) / 两次采样间隔(分钟)

用法：
  # 用配置里的默认组跑（默认 60s × 5 轮）
  python skillhub_download_monitor.py

  # 指定组
  python skillhub_download_monitor.py --group "另一组"

  # 临时追加一个 slug（覆盖配置）
  python skillhub_download_monitor.py --slug "@org-xxx/yyy" --slug "@org-xxx/zzz"

  # 覆盖采样参数 + 写 CSV
  python skillhub_download_monitor.py --interval 3600 --rounds 30 --csv growth.csv
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("缺少 requests 依赖：pip install requests")
    sys.exit(1)

API = "https://api.skillhub.cn/api/v1/skills/batch"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config(path=CONFIG_PATH):
    """读config.json，返回 (settings, groups)"""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"找不到配置文件：{path}\n"
            f"请复制一份示例并按需修改。"
        )
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg.get("settings") or {}, cfg.get("groups") or []


def pick_group(groups, name=None):
    """按名字取组；不给名字则取 enabled=true 的第一个；都没有则取第一组"""
    if not groups:
        raise ValueError("config.json 里 groups 为空，没有任何可监控的 skill")
    if name:
        for g in groups:
            if g.get("name") == name:
                return g
        avail = "、".join(g.get("name", "(未命名)") for g in groups)
        raise ValueError(f"找不到组 '{name}'。可用组：{avail}")
    for g in groups:
        if g.get("enabled"):
            return g
    return groups[0]


def resolve_slugs(group, only_enabled=True):
    """从组里取出 slug 列表"""
    out = []
    for s in (group.get("skills") or []):
        if only_enabled and s.get("enabled") is False:
            continue
        slug = (s.get("slug") or "").strip()
        if slug:
            out.append(slug)
    return out


def fetch_downloads(slugs, timeout=30):
    """一次批量拉取多个 skill 的累计下载量，返回 (dict, missing list)"""
    resp = requests.post(API, json={"slugs": slugs}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    out = {}
    for item in data.get("items", []):
        canon = (item.get("namespace") or {}).get("canonicalName")
        stats = (item.get("skill") or {}).get("stats") or {}
        if canon:
            out[canon] = {
                "downloads": stats.get("downloads", 0),
                "stars": stats.get("stars", 0),
                "installs": stats.get("installs", 0),
                "versions": stats.get("versions", 0),
                "comments": stats.get("comments", 0),
            }

    missing = data.get("missing") or []
    return out, missing


def main():
    ap = argparse.ArgumentParser(
        description="SkillHub 下载量增长监控（监控对象读config.json，代码内不写死）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--config", default=CONFIG_PATH, help="配置文件路径，默认同目录 config.json")
    ap.add_argument("--group", help="config.json 里的组名；不给则用 enabled=true 的组")
    ap.add_argument("--slug", action="append", help="临时指定 slug（可重复），会覆盖配置里的清单")
    ap.add_argument("--interval", type=int, help="采样间隔秒数；不给则用配置里的值")
    ap.add_argument("--rounds", type=int, help="采样轮数；不给则用配置里的值")
    ap.add_argument("--csv", help="把每次采样与增量写入 CSV")
    args = ap.parse_args()

    try:
        settings, groups = load_config(args.config)
    except Exception as e:
        print(f"[错误] 读取配置失败：{e}")
        return 1

    # 命令行 slug 优先，其次指定组，最后默认组
    if args.slug:
        slugs = list(dict.fromkeys(args.slug))  # 去重且保序
        group_name = "命令行指定"
    else:
        try:
            grp = pick_group(groups, args.group)
        except ValueError as e:
            print(f"[错误] {e}")
            return 1
        slugs = resolve_slugs(grp)
        group_name = grp.get("name", "(未命名)")

    if not slugs:
        print(f"[错误] 组「{group_name}」里没有启用任何 skill。"
              f"请编辑 {args.config}")
        return 1

    interval = args.interval if args.interval is not None else settings.get("interval", 60)
    rounds = args.rounds if args.rounds is not None else settings.get("rounds", 5)

    prev = None
    prev_ts = None
    rows = []  # [time, slug, downloads, delta, per_min]
    total_delta = {s: 0 for s in slugs}

    print(f"配置：{args.config}")
    print(f"组「{group_name}」· 监控 {len(slugs)} 个 skill · 间隔 {interval}s · 共 {rounds} 轮\n")

    for r in range(rounds):
        try:
            cur, missing = fetch_downloads(slugs)
        except Exception as e:
            print(f"[第 {r+1} 轮] 请求失败：{e}")
            if r < rounds - 1:
                time.sleep(interval)
            continue

        if not cur:
            print(f"[第 {r+1} 轮] 上游未返回任何 Skill 数据。"
                  f"常见原因：Skill 已下架/改名，或 config.json 里的 slug 有误。")
            if r < rounds - 1:
                time.sleep(interval)
            continue

        if missing:
            print(f"[第 {r+1} 轮] [警告] {len(missing)} 个 Skill 不存在（可能已下架或改名）：")
            for m in missing:
                print(f"        - {m}")

        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")

        if prev is None:
            print(f"[{ts}] 基线采样完成（第 1 轮，无增量）")
            for s in slugs:
                d = cur.get(s)
                print(f"    {s:<48} 累计 {d['downloads']:>10,}" if d else f"    {s:<48} 已下架/无数据")
        else:
            gap_min = (now - prev_ts).total_seconds() / 60.0
            print(f"[{ts}] 距上次 {gap_min*60:.0f}s")
            for s in slugs:
                d2 = cur.get(s)
                d1 = prev.get(s)
                if not d2 or not d1:
                    print(f"    {s:<48} 已下架/无数据")
                    continue
                delta = d2["downloads"] - d1["downloads"]
                per_min = delta / gap_min if gap_min > 0 else 0
                total_delta[s] += delta
                rows.append([now.isoformat(timespec="seconds"), s, d2["downloads"], delta, round(per_min, 4)])
                sign = "+" if delta >= 0 else ""
                print(f"    {s:<48} 累计 {d2['downloads']:>10,}  增量 {sign}{delta:<6,}  ≈ {sign}{per_min:.2f}/分钟")

        prev, prev_ts = cur, now

        if r < rounds - 1:
            time.sleep(interval)

    # 汇总
    if rows:
        span_min = ((rounds - 1) * interval) / 60.0
        print("\n" + "=" * 74)
        print(f"汇总（{rounds} 轮采样，总时长约 {(rounds-1)*interval}s）")
        print("=" * 74)
        for s in slugs:
            d = total_delta[s]
            avg = d / span_min if span_min > 0 else 0
            print(f"  {s:<48} 总增量 {d:>8,}  平均 {avg:>7.4f}/分钟")
        print("=" * 74)

    if args.csv and rows:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["time", "slug", "downloads", "delta", "per_minute"])
            w.writerows(rows)
        print(f"\nCSV 已写入：{args.csv}")
    elif args.csv:
        print("\n无有效样本（不足 2 轮），未写 CSV。")

    return 0


if __name__ == "__main__":
    sys.exit(main())