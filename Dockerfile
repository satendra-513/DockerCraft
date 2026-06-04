# Stage 1: Build the Vite Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Run the FastAPI Backend
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies (git is needed for cloning, build-essential for building python extensions if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY backend/app ./app

# Copy the frontend built assets to the expected relative path
# backend/app/main.py looks for "../../frontend/dist" which maps to /frontend/dist
COPY --from=frontend-builder /frontend/dist /frontend/dist

# Expose port 8000
EXPOSE 8000

# Set Environment Variables
ENV PYTHONUNBUFFERED=1

# Command to run uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
