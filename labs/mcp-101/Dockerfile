FROM python:3.13-slim
RUN pip install --no-cache-dir 'fastmcp>=2.13,<3'
WORKDIR /app
COPY server.py .
EXPOSE 8000
CMD ["fastmcp", "run", "server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
