# ==============================================================================
# WebGlancer - Visual Change Monitoring Suite Dockerfile
# Base Image: Official Microsoft Playwright Python (includes Chromium & OS deps)
# ==============================================================================

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set Environment Variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Kolkata \
    DEBIAN_FRONTEND=noninteractive

# Set Working Directory
WORKDIR /app

# Copy Requirements and Install Python Dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy Application Source Code
COPY visual_change_detector.py /app/
COPY website_change_detect.py /app/
COPY domain.txt /app/
COPY monitor /app/monitor

# Create persistent cache directory structure
RUN mkdir -p /app/.visual_cache/baselines \
             /app/.visual_cache/latest \
             /app/.visual_cache/diffs \
             /app/.visual_cache/history

# Expose Web Dashboard & REST API Port
EXPOSE 8087

# Health Check to ensure REST API is healthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8087/api/status || exit 1

# Default Command: Launch REST API & Dashboard Server with Background Scheduler
CMD ["python", "visual_change_detector.py", "serve", "--host", "0.0.0.0", "--port", "8087", "--no-browser"]
