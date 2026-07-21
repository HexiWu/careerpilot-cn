FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAREERPILOT_DATABASE=/app/data/careerpilot.db

WORKDIR /app

RUN addgroup --system careerpilot && adduser --system --ingroup careerpilot careerpilot

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

RUN mkdir -p /app/data && chown -R careerpilot:careerpilot /app
USER careerpilot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["careerpilot", "serve", "--host", "0.0.0.0", "--port", "8000"]
