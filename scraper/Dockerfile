FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Install uv for dependency management
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app ./app

ENV PYTHONUNBUFFERED=1
ENV PORT=3000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
