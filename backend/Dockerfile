FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 antecipe

COPY app/ ./app/
COPY data/validadores_antecipe.json data/cnpj_situacao_mock.csv ./data/

USER antecipe
EXPOSE 8000

CMD ["python", "-m", "app.server"]
