# Build context is the REPO ROOT, not backend/.
# config.py derives assets_dir as <repo root>/assets, so the image must contain
# both backend/ and assets/ in that same relative layout or every check that
# reads the roster / sponsor manifest / brand guide / safe zones will crash.
FROM python:3.11-slim

# opencv-python-headless needs libglib even though it skips the GUI stack.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app  backend/app
COPY assets       assets

# WORKDIR must be /app/backend so that:
#   - "app.main:app" is importable
#   - BACKEND_DIR resolves to /app/backend  -> data/ lands where the volume is
#   - REPO_ROOT resolves to /app            -> assets/ is found
WORKDIR /app/backend

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
