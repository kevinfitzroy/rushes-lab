# Seahub PoC 配置覆盖 — 落地 v0.4 §3.2/§6.3 P5 修订
#
# 该文件挂为容器内 /shared/seafile/conf/seahub_settings.override.py(Seafile 会 import 这个 override)

# ─── 关键:关闭 Seafile 内置视频缩略图(v0.4 §6.3 P5 修订)───
# Seafile 内置 thumbnail-server 启用视频缩略图后,大量视频并发会 DoS 服务器(issue #2168)。
# PoC 阶段缩略图责任由 FastAPI 旁路接管(通过 MinIO bucket event 异步生成,落 dataset B)。
ENABLE_VIDEO_THUMBNAIL = False

# 图片缩略图保留(无 DoS 报告,Seafile 内置即可)
ENABLE_THUMBNAIL = True

# 文件类型识别(MimeType)— 让 Seafile Web 正确识别视频文件,展示 video icon
# Seafile 默认支持常见 mime,这里只标 explicit 防回归
# (Seafile 13.0+ 自带,无需手配)

# ─── 性能 ───
# 大量小文件场景(blocks 在 MinIO 里成千上万),减少 webdav request 超时影响
WEBDAV_REQUEST_TIMEOUT = 300  # seconds
