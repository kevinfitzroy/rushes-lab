#!/usr/bin/env python3
"""
合成视频文件数据集生成器(material-storage PoC issue #11)。

两种模式:
  - sparse  : 用 os.truncate 创建 sparse 文件,几乎不占磁盘空间,只占 inode +
              filesystem metadata。适合测目录扫描 / oc_filecache 增长 / 桌面客户端 listing。
              FFmpeg / NC preview:generate 在 sparse 空文件上会报错。
  - realistic: 复制一个小 sample mp4(用户提供 --sample),为每个目标文件创建
               hardlink,几乎不占额外磁盘。适合测 preview 生成、缩略图、WebDAV 下载。
               注意:hardlink 共享 inode,NC 看到的是相同内容,这对 oc_filecache 维度
               的"百万独立文件"已经够用;对内容指纹去重相关测试可能误差。

用法:
  python gen.py \\
      --count 1000 \\
      --output /srv/poc-data/dataset-small \\
      --avg-size-mb 150 \\
      --seed 42

  python gen.py --count 500000 --output /srv/poc-data/dataset-50w \\
      --mode realistic --sample /tmp/sample-1mb.mp4

参数:
  --count                总文件数(PoC 阶段 1000 起步;Stage 2 性能测 5e5 或 1e6)
  --output               输出根目录;脚本会在此下创建 user_xxx/project_x/shot_xxx.mp4
  --mode                 sparse(默认)| realistic
  --sample               realistic 模式必填,sample mp4 路径(几 MB 以内为佳)
  --avg-size-mb          sparse 模式下平均文件大小(影响 stat() 报告的 size,不占磁盘)
  --size-distribution    uniform | gaussian | heavy-tail(默认 gaussian)
  --users                虚拟用户数(默认 20)
  --projects-per-user    每用户项目数(默认 5)
  --files-per-project-min 每项目文件数下限(默认 5)
  --files-per-project-max 每项目文件数上限(默认 200)
  --seed                 随机种子(reproducibility)
  --manifest             生成 manifest 文件名(默认 MANIFEST.json,在 --output 根)
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path


def pick_size(rng: random.Random, mode: str, avg_mb: int) -> int:
    """返回文件期望大小(bytes)。"""
    if mode == "uniform":
        return int(rng.uniform(0.5 * avg_mb, 1.5 * avg_mb) * 1024 * 1024)
    if mode == "gaussian":
        size = max(1, int(rng.gauss(avg_mb, avg_mb * 0.3)))
        return size * 1024 * 1024
    if mode == "heavy-tail":
        # 90% 小文件(≤ avg),10% 大文件(可达 5x avg);模拟短视频 + 偶尔大原片
        if rng.random() < 0.9:
            return int(rng.uniform(0.1, 1.0) * avg_mb) * 1024 * 1024
        return int(rng.uniform(1.0, 5.0) * avg_mb) * 1024 * 1024
    raise ValueError(f"unknown size-distribution: {mode}")


def plan_layout(args, rng: random.Random):
    """按 users × projects × files-per-project 规划文件树,返回 [(rel_path, size), ...]。"""
    plan = []
    remaining = args.count
    user_ids = [f"user_{i+1:03d}" for i in range(args.users)]
    rng.shuffle(user_ids)

    # 简单方案:平均分到每个用户,每用户均匀分到 projects
    while remaining > 0 and user_ids:
        uid = user_ids[remaining % len(user_ids)]
        for pidx in range(args.projects_per_user):
            if remaining <= 0:
                break
            pname = f"project_{chr(ord('a') + pidx)}"
            files_in_proj = rng.randint(
                args.files_per_project_min,
                args.files_per_project_max,
            )
            files_in_proj = min(files_in_proj, remaining)
            for j in range(files_in_proj):
                fname = f"shot_{rng.randint(0, 10**8):08d}.mp4"
                rel = f"{uid}/{pname}/{fname}"
                size = pick_size(rng, args.size_distribution, args.avg_size_mb)
                plan.append((rel, size))
                remaining -= 1
        if user_ids and len(plan) % (args.users * args.projects_per_user) == 0:
            user_ids.pop(0)
            user_ids.append(uid)  # round-robin
    return plan


def create_sparse(root: Path, rel: str, size: int):
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    # truncate 创建 sparse 文件,不实际写入数据
    with open(full, "wb") as f:
        os.truncate(f.fileno(), size)


def create_hardlink(root: Path, rel: str, sample: Path):
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    os.link(sample, full)


def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--mode", choices=["sparse", "realistic"], default="sparse")
    ap.add_argument("--sample", help="realistic 模式必填的 sample mp4 路径")
    ap.add_argument("--avg-size-mb", type=int, default=150)
    ap.add_argument("--size-distribution", choices=["uniform", "gaussian", "heavy-tail"], default="gaussian")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--projects-per-user", type=int, default=5)
    ap.add_argument("--files-per-project-min", type=int, default=5)
    ap.add_argument("--files-per-project-max", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--manifest", default="MANIFEST.json")
    args = ap.parse_args()

    if args.mode == "realistic" and not args.sample:
        ap.error("--mode realistic 必须搭配 --sample <sample.mp4>")

    rng = random.Random(args.seed)
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    sample = Path(args.sample).resolve() if args.sample else None

    print(f"[gen] count={args.count} mode={args.mode} output={root} seed={args.seed}", file=sys.stderr)
    t0 = time.time()
    plan = plan_layout(args, rng)
    print(f"[gen] planned {len(plan)} files in {time.time()-t0:.1f}s", file=sys.stderr)

    created = 0
    t0 = time.time()
    for rel, size in plan:
        if args.mode == "sparse":
            create_sparse(root, rel, size)
        else:
            create_hardlink(root, rel, sample)
        created += 1
        if created % 10000 == 0:
            rate = created / (time.time() - t0)
            print(f"[gen] {created}/{len(plan)} files ({rate:.0f}/s)", file=sys.stderr)

    manifest_path = root / args.manifest
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "mode": args.mode,
                "count": len(plan),
                "avg_size_mb": args.avg_size_mb,
                "size_distribution": args.size_distribution,
                "seed": args.seed,
                "generated_at": int(time.time()),
                "sample_path": str(sample) if sample else None,
                "files": [{"rel": rel, "expected_size": sz} for rel, sz in plan],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"[gen] done: {created} files, manifest at {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
