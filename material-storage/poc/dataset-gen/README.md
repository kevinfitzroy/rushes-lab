# dataset-gen

合成视频文件数据集生成器(对应 issue #11)。

## 快速跑

```bash
# 小规模(Stage 1 功能验证,几秒完成)
python gen.py --count 1000 --output /srv/poc-data/dataset-small --seed 42

# 中规模(50w,~5-20 分钟,占磁盘 minimal)
python gen.py --count 500000 --output /srv/poc-data/dataset-50w --seed 42

# 真实可预览的小数据集(需要 sample mp4)
ffmpeg -f lavfi -i testsrc=duration=1:size=320x240:rate=10 -t 1 /tmp/sample-1mb.mp4
python gen.py --count 10000 --output /srv/poc-data/dataset-real \\
    --mode realistic --sample /tmp/sample-1mb.mp4 --seed 42
```

## 模式选择

| 测试目的 | 推荐 mode |
| --- | --- |
| 目录扫描 / files:scan / oc_filecache 增长 / 桌面 listing | **sparse**(几乎不占磁盘) |
| preview:generate-all / 缩略图 / WebDAV 真实下载吞吐 | **realistic**(hardlink 一个 sample mp4) |

混合方式也行:同一目录下 70% sparse + 30% realistic,模拟"大部分文件已索引、部分需要预览" 的真实场景。当前 gen.py 不直接支持混合,要混合就跑两次到不同子目录。

## 输出

数据集根目录下产出:

```
<output>/
├── user_001/
│   ├── project_a/
│   │   ├── shot_12345678.mp4
│   │   ├── ...
│   ├── project_b/
├── user_002/
├── ...
└── MANIFEST.json     # 元数据 + 文件清单,供测试脚本 cross-check
```

`MANIFEST.json` 字段:

```json
{
  "version": 1,
  "mode": "sparse",
  "count": 500000,
  "avg_size_mb": 150,
  "size_distribution": "gaussian",
  "seed": 42,
  "generated_at": 1715760000,
  "sample_path": null,
  "files": [
    {"rel": "user_001/project_a/shot_12345678.mp4", "expected_size": 157286400},
    ...
  ]
}
```

## 已知限制

- **sparse 模式下 NC `preview:generate-all` 会失败**(FFmpeg 不识别空 mp4);只在 sparse + 不测 preview 的场景下用
- **realistic 模式 hardlink 在跨文件系统时失败**;sample 与 output 须在同一 mount
- 磁盘 IO 速度限制:NVMe 上 50w 文件 sparse 约 5-20 分钟,HDD 慢一档
- 没有清理脚本,删数据集用 `rm -rf <output>`

## 验收(issue #11)

- [ ] 50w 数据集生成 ≤ 4h(NVMe + ZFS)
- [ ] MANIFEST 完整,目录结构可读
- [ ] sparse 模式磁盘占用 < 1 GB(实测)
- [ ] realistic 模式磁盘占用 ≈ sample 大小(hardlink 共享 inode)
