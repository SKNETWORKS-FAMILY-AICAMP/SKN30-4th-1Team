# PaiM 백엔드 API 이미지.
#
# 베이스는 .python-version(3.14)과 맞춘다. uv.lock이 이 인터프리터로 해석되어
# 있으므로 다른 버전을 쓰면 재해석이 일어나 재현 가능한 빌드가 아니게 된다.
FROM python:3.14-slim

# uv는 공식 배포 이미지에서 바이너리만 복사한다(설치 스크립트보다 빠르고 고정적).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1단계: 의존성만 설치한다. 소스가 바뀌어도 이 레이어는 캐시에서 재사용되므로
# t3.small(2GB)에서 재빌드 시간을 크게 줄인다.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2단계: 백엔드 소스 복사 후 프로젝트 자체를 설치한다.
#
# 리포지토리 루트를 통째로 COPY하지 않는다 — .dockerignore가 있어도 명시적 복사가
# 비밀 파일 유입에 대한 더 강한 보장이다.
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# 비루트 실행. 볼륨 마운트 지점을 미리 만들고 소유권을 넘겨야 컨테이너가
# 업로드·벡터를 쓸 수 있다(마운트 시 디렉터리 소유권은 이미지 것을 따른다).
RUN useradd --create-home --uid 10001 paim \
    && mkdir -p /app/data/uploads /app/.chroma \
    && chown -R paim:paim /app/data /app/.chroma
USER paim

EXPOSE 8000

# serve()를 우회해 컨테이너 안에서 명시적으로 바인딩한다.
#
# --workers 1은 반드시 명시한다. 생략하면 uvicorn이 WEB_CONCURRENCY 환경변수를
# 읽어(uvicorn/config.py의 workers is None 분기) 외부 env가 워커 수를 결정한다.
# 워커가 2개 이상이면 두 가지가 깨진다:
#   1. GitHub App 설치 세션이 인메모리 dict(backend/github/router.py)라 요청이
#      다른 워커로 가면 state를 찾지 못한다.
#   2. Chroma 임베디드 PersistentClient가 벡터 디렉터리를 단일 점유한다.
# 운영 compose도 WEB_CONCURRENCY=1을 고정해 이중으로 막는다.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
