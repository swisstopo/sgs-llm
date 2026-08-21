FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SWISSTOPO_MCP_HOST=0.0.0.0 \
    SWISSTOPO_MCP_PORT=8000 \
    SWISSTOPO_MCP_TRANSPORT=http

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3))['status'] == 'ok'"

CMD ["swisstopo-search-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
