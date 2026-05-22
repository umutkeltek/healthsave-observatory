FROM python:3.12-slim

ENV PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/server/ ./server/
COPY apps/worker/worker/ ./worker/
COPY packages/py/analysis/ ./analysis/
COPY packages/py/compat_v1/ ./compat_v1/
COPY packages/py/contracts/ ./contracts/
COPY packages/py/db/ ./db/
COPY packages/py/plugin_sdk/ ./plugin_sdk/
COPY packages/py/homeassistant_mqtt/ ./homeassistant_mqtt/
COPY packages/py/runtime/ ./runtime/
COPY packages/py/storage/ ./storage/
COPY plugins/ ./plugins/
COPY db/migrations/ ./db/migrations/
COPY scripts/ ./scripts/

USER appuser
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
