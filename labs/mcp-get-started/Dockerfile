FROM python:3.13-slim
# Same floor as pyproject.toml. 4.0.2 is the first release carrying the tasks
# behaviour this lab walks through.
RUN pip install --no-cache-dir 'fastmcp[tasks]>=4.0.2,<5'
WORKDIR /app
COPY server.py .
EXPOSE 8000
# Readiness for `docker compose up --wait`, which returns only once this passes.
# The image has no curl, so probe with the interpreter that is already here.
HEALTHCHECK --interval=2s --timeout=3s --start-period=2s --retries=15 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["fastmcp", "run", "server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
