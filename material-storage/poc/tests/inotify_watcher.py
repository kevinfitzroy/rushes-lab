#!/usr/bin/env python3
"""
PoC inotify watcher — 验证 v0.3 §3.3 数据流约束 "底座 → FastAPI 单向只读"
+ §3.4 路径过滤(忽略 appdata_*, files_trashbin/, files_versions/)。

不做实际缩略图 / AI 索引 — 只统计 event 类型 / 速率,验证 throughput +
路径过滤是否生效。

用法:
    pip install inotify-simple
    python inotify_watcher.py \\
        --watch /srv/poc-data/nc-data \\
        --exclude appdata_ files_trashbin files_versions

输出:
    CSV 格式 stdout,每秒 metrics 一行:
        timestamp,events_total,events_filtered,events_passed,rate_per_sec

按 Ctrl+C 退出,会打印 summary。
"""

import argparse
import os
import signal
import sys
import time
from pathlib import Path

try:
    from inotify_simple import INotify, flags
except ImportError:
    print("missing dependency: pip install inotify-simple", file=sys.stderr)
    sys.exit(1)


def should_filter(path: str, exclude_patterns: list[str]) -> bool:
    """检查路径是否匹配任一过滤模式(简单 substring 匹配)。"""
    for pat in exclude_patterns:
        if pat in path:
            return True
    return False


def add_watches(inotify: INotify, root: Path, exclude_patterns: list[str]) -> dict[int, Path]:
    """递归 add_watch 给所有子目录,返回 wd→path 映射。"""
    watches: dict[int, Path] = {}
    watch_flags = (
        flags.CREATE | flags.MODIFY | flags.MOVED_TO | flags.MOVED_FROM | flags.DELETE | flags.CLOSE_WRITE
    )

    skipped_dirs = 0
    for dirpath, dirnames, _ in os.walk(root):
        # 在 walk 期间裁剪子目录,避免下沉到要过滤的子树
        dirnames[:] = [d for d in dirnames if not should_filter(d, exclude_patterns)]
        if should_filter(dirpath, exclude_patterns):
            skipped_dirs += 1
            continue
        try:
            wd = inotify.add_watch(dirpath, watch_flags)
            watches[wd] = Path(dirpath)
        except OSError as e:
            print(f"[watch] failed on {dirpath}: {e}", file=sys.stderr)

    print(
        f"[watch] {len(watches)} dirs watched, {skipped_dirs} subtrees skipped by filter",
        file=sys.stderr,
    )
    return watches


def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    ap.add_argument("--watch", required=True, help="底座 datadirectory 根路径")
    ap.add_argument(
        "--exclude",
        nargs="*",
        default=["appdata_", "files_trashbin", "files_versions"],
        help="路径过滤 substring(默认覆盖 NC 三个旁路绝不能进的子目录)",
    )
    ap.add_argument("--interval", type=float, default=1.0, help="metrics 输出间隔秒数")
    args = ap.parse_args()

    root = Path(args.watch).resolve()
    if not root.is_dir():
        print(f"watch root not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    inotify = INotify()
    watches = add_watches(inotify, root, args.exclude)

    total = 0
    filtered = 0
    passed = 0

    def summary(*_):
        print(
            f"\n[summary] total={total} filtered={filtered} passed={passed}",
            file=sys.stderr,
        )
        sys.exit(0)

    signal.signal(signal.SIGINT, summary)
    signal.signal(signal.SIGTERM, summary)

    # CSV header
    print("timestamp,events_total,events_filtered,events_passed,rate_per_sec")
    last_total = 0
    last_t = time.time()

    while True:
        events = inotify.read(timeout=int(args.interval * 1000))
        for ev in events:
            total += 1
            wd_path = watches.get(ev.wd)
            full_name = f"{wd_path}/{ev.name}" if wd_path else ev.name
            if should_filter(full_name, args.exclude):
                filtered += 1
            else:
                passed += 1
                # 如果是新目录,递归 add_watch
                if ev.mask & flags.CREATE and (wd_path / ev.name).is_dir():
                    try:
                        new_wd = inotify.add_watch(
                            str(wd_path / ev.name),
                            flags.CREATE | flags.MODIFY | flags.MOVED_TO | flags.MOVED_FROM | flags.DELETE | flags.CLOSE_WRITE,
                        )
                        watches[new_wd] = wd_path / ev.name
                    except OSError:
                        pass

        now = time.time()
        if now - last_t >= args.interval:
            rate = (total - last_total) / (now - last_t)
            print(f"{int(now)},{total},{filtered},{passed},{rate:.1f}", flush=True)
            last_total = total
            last_t = now


if __name__ == "__main__":
    main()
