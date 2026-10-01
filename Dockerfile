FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages packages
COPY services services

ENV PYTHONPATH=/srv/packages/engram_contracts:/srv/services/gateway:/srv/services/character:/srv/services/conversation:/srv/services/memory:/srv/services/harness
ENV PYTHONUNBUFFERED=1

EXPOSE 18410
CMD ["python", "-m", "uvicorn", "gateway_service.main:app", "--host", "0.0.0.0", "--port", "18410"]
