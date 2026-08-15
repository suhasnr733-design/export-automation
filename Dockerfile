# ==============================================================================
# Dockerfile for API 3 - EXPORT Automation System
# Python 3.12 Production Container with Gunicorn WSGI Server & TEST_MODE Safety
# ==============================================================================

FROM python:3.12-slim

# Build-time and runtime flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEST_MODE=true \
    PORT=5000 \
    FLASK_ENV=production

# Install curl for container health-check probing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged application user for security
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=appuser:appgroup . .

# Ensure data and assets directories exist with correct permissions
RUN mkdir -p /app/data /app/assets && \
    chmod +x /app/entrypoint.sh && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose HTTP service port
EXPOSE 5000

# Container healthcheck querying the lightweight /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Launch container via entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
