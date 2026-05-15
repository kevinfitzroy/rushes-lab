# Seahub PoC 配置覆盖 — 落地 v0.5 §3.2/§6.3 finding 修订
#
# 文件挂为容器内 /shared/seafile/conf/local_settings.py
# (v0.4 用 seahub_settings.override.py 名,实测 Seafile 不自动 import 该后缀 — F-3 修复)
#
# Seafile 的 seahub/seahub/settings.py 会自动 import seahub.local_settings,这是
# 官方支持的扩展点,无需改 Seafile 源码

# ─── 关键:关闭 Seafile 内置视频缩略图(v0.5 §3.2.0 三弱点应对 + §6.3 P5 修订)───
# Seafile 内置 thumbnail-server 启用视频缩略图后,大量视频并发会 DoS 服务器(issue #2168)。
# PoC 阶段缩略图责任由 FastAPI 旁路接管 —— MinIO bucket event 触发后 ffmpeg 转 720p
# 代理版到 dataset B(POSIX 直读),作为 Web 播放 / 审批播放 / AI pipeline 共用源。
ENABLE_VIDEO_THUMBNAIL = False

# 图片缩略图保留(无 DoS 报告,Seafile 内置即可)
ENABLE_THUMBNAIL = True

# 文件类型识别(MimeType)— Seafile Web 正确识别视频文件,展示 video icon
# Seafile 默认支持常见 mime,这里只标 explicit 防回归(Seafile 13.0+ 自带)

# ─── 性能 ───
# 大量小文件场景(blocks 在 MinIO 里成千上万),减少 webdav request 超时影响
WEBDAV_REQUEST_TIMEOUT = 300  # seconds
