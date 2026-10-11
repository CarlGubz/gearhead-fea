FROM python:3.12-slim

WORKDIR /app

# Gmsh (CAD import: STEP / IGES / STL) needs a few shared libraries that the slim image does not ship
RUN apt-get update && apt-get install -y --no-install-recommends         libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libfontconfig1 libgomp1     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
USER app

EXPOSE 8000
# --proxy-headers: trust X-Forwarded-* from nginx. The backend port is NOT
# published to the host, so only the nginx container can reach it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
