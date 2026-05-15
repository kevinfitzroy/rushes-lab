# tests/ — PoC 测试脚本

本目录覆盖 issue #14 的部分(通用、不依赖具体底座的旁路与 e2e 测试)+ 部分 #12 / #13 共用基准。底座特异的指标(NC `oc_filecache` / oCIS xattr 等)在各路线 README 里描述,本目录暂不提供。

## 已就位

### `inotify_watcher.py`

验证 v0.3 §3.3 "底座 → FastAPI 单向只读" + §3.4 路径过滤:

```bash
pip install inotify-simple
python inotify_watcher.py \\
    --watch /srv/poc-data/nc-data \\
    --exclude appdata_ files_trashbin files_versions \\
    > inotify-metrics.csv
```

跟跑 NC 写入(用户上传 / cron 预览生成),观察:

- `events_filtered` 应该**显著大于 0**(NC 自己写 appdata_*)
- `events_passed` 在用户实际上传时上升

输出 CSV 每秒一行,可 plot 或导入 Excel 看节奏。

## 待写(issue #12/#13/#14 验收用)

| 脚本 | 用途 | 状态 |
| --- | --- | --- |
| `nc_baseline.sh` | 跑 NC 5 项性能指标(目录浏览延迟 / files:scan / preview:generate / oc_filecache 增长 / 桌面冲突) | TODO |
| `ocis_baseline.sh` | 跑 oCIS 同等指标 + xattr 验证 + 客户端兼容 | TODO |
| `sensitive_download_e2e.py` | 模拟 §4 (b) 方案:用户在底座见文件 → 跳 FastAPI → 飞书审批 mock → 签名 URL → 下载 → 审计 | TODO(依赖飞书 bridge MS-FB-001 实施) |

## 资源

- `inotify-simple`(Python 库,pure Python wrapper):https://pypi.org/project/inotify-simple/
- 视频缩略图 baseline 跑出来要 ffmpeg 装在 NC 容器里(见 `../nc/README.md` 末尾的 apt-install 提示)
