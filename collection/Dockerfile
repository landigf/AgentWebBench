# AgentWebBench v2 — Reproducible collection container
# Build from SpotAIfy root: docker build -f asl-project/benchmarks/Dockerfile -t agentwebbench-runner:v2 .
FROM python:3.12-slim

# Browser dependencies for Chromium / Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY asl-project/benchmarks/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && playwright install chromium --with-deps

# Copy project files needed for collection
COPY trace_schema.py /app/trace_schema.py
COPY asl-project/benchmarks/ /app/asl-project/benchmarks/
COPY asl-project/instrumentation/ /app/asl-project/instrumentation/

WORKDIR /app/asl-project/benchmarks

# Default: show help. Override CMD to run collection.
ENTRYPOINT ["python", "runner.py"]
CMD ["--help"]
