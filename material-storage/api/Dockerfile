# material-storage-api Dockerfile — Phase B-2
# 单 stage,清华 pip 源(避 GFW + 跳 uv ghcr.io 依赖)

FROM python:3.12-slim

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update -qq \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
 && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts

EXPOSE 8000
# --proxy-headers + --forwarded-allow-ips '*':信任 nginx 注入的 X-Forwarded-Proto,
# 否则 StaticFiles 的 trailing-slash 307 会用 http:// 重定向,公网 https 用户跳到 http 链
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
