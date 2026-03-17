FROM python:3.12-slim

WORKDIR /workspace/backend
COPY backend/requirements-dev.txt backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
