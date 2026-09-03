# material-storage-api Dockerfile — Phase B-2
# 单 stage,默认清华源(避 GFW + 跳 uv ghcr.io 依赖)
# apt / pip 源可经 build arg 覆盖(部分网络对清华源包文件 403,如换阿里云:
#   docker compose build --build-arg … 不支持,用环境变量 APT_MIRROR / PIP_INDEX_URL,
#   见 docker-compose.yml build.args 与 scripts/local_up.sh)

FROM python:3.12-slim

ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
 && apt-get update -qq \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && pip config set global.index-url ${PIP_INDEX_URL}

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
