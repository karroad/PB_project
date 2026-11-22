FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt
COPY app ./app
RUN useradd -m siteforge && mkdir -p /app/data && chown -R siteforge /app
USER siteforge
# Claude Code CLI (native install) so CONTENT can run on the monthly Claude subscription
# after an interactive `claude login`. Credentials/config persist in the data volume
# via CLAUDE_CONFIG_DIR, so a single login survives container restarts and is shared by all workers.
ENV PATH="/home/siteforge/.local/bin:${PATH}" CLAUDE_CONFIG_DIR=/app/data/claude
RUN curl -fsSL https://claude.ai/install.sh | bash || echo "claude CLI install skipped (install later)"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
