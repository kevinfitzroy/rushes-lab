<?php
// Nextcloud 自定义配置 — 落地 v0.3 §8 部署最小配置(PHP 段)。
// 该文件挂为容器 /var/www/html/config/custom.config.php(NC 会与 config.php merge)。

$CONFIG = [
  // ─── 缓存与锁(v0.3 §8) ───
  'memcache.local' => '\OC\Memcache\APCu',
  'memcache.distributed' => '\OC\Memcache\Redis',
  'memcache.locking' => '\OC\Memcache\Redis',
  'redis' => [
    'host' => 'nc-redis',
    'port' => 6379,
    'timeout' => 1.5,
  ],

  // ─── 预览生成限制(v0.3 §8 limit preview size) ───
  'preview_max_x' => 2048,
  'preview_max_y' => 2048,
  // 启用视频预览(需要 ffmpeg,nextcloud:30-apache 镜像默认未装,要在容器内 apt install ffmpeg)
  'enabledPreviewProviders' => [
    'OC\\Preview\\Image',
    'OC\\Preview\\Movie',
    'OC\\Preview\\MP3',
    'OC\\Preview\\TXT',
    'OC\\Preview\\Markdown',
    'OC\\Preview\\PDF',
  ],

  // ─── 日志 ───
  'log_type' => 'file',
  'logfile' => '/var/log/nextcloud.log',
  'loglevel' => 2,  // WARN 起;PoC 调试时改 0 (DEBUG)

  // ─── 性能 / 安全(PoC 简化) ───
  'maintenance' => false,
  'auth.bruteforce.protection.enabled' => true,
];
