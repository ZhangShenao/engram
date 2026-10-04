FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /srv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY packages packages
COPY services services
COPY proto proto

ENV PATH=/srv/.venv/bin:$PATH
ENV PYTHONPATH=/srv/packages/engram_contracts:/srv/packages/engram_queue:/srv/services/chat:/srv/services/context:/srv/services/memory:/srv/services/llm_gateway
ENV PYTHONUNBUFFERED=1

EXPOSE 18410
CMD ["python", "-m", "uvicorn", "chat_service.main:app", "--host", "0.0.0.0", "--port", "18410"]
