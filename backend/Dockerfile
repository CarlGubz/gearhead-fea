FROM python:3.11-slim

WORKDIR /app

# (Optional) Install CalculiX from Debian repos so the app uses the real
# industrial solver instead of the built-in fallback. Comment out if you
# don't need it / want a smaller image - the app works fine without it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends calculix-ccx \
    && rm -rf /var/lib/apt/lists/* || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV DATABASE_URL=sqlite:///./data/webfea.db
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
