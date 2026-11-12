FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY src ./src
RUN pip install --no-cache-dir -e .

CMD ["alembic", "upgrade", "head"]