# Image d'execution du moteur PolyTrade.
#
#   docker build -t polytrade .
#   docker run --rm -p 8000:8000 -e POLY_DEMO_MODE=true polytrade
#
# Construction en deux etapes : les dependances sont installees dans un venv
# de la premiere etape, puis seul ce venv est copie. L'image finale ne
# contient donc ni compilateur ni cache pip.

FROM python:3.12-slim AS builder

# Les roues de pycryptodome et ckzg peuvent necessiter une compilation selon
# l'architecture : le compilateur reste confine a cette etape.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiee seule pour que la couche de dependances soit mise en cache tant que
# requirements.txt ne change pas.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

# Utilisateur non privilegie : ce service peut detenir une cle capable de
# signer, il n'a aucune raison de tourner en root.
RUN useradd --create-home --uid 10001 polytrade

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=polytrade:polytrade src/ ./src/
COPY --chown=polytrade:polytrade web/ ./web/
COPY --chown=polytrade:polytrade main.py .env.example ./

USER polytrade
EXPOSE 8000

# 0.0.0.0 dans le conteneur : c'est la publication de port de Docker qui
# decide de l'exposition reelle. Par defaut `docker run -p 127.0.0.1:8000:8000`
# garde l'ecoute locale — ne publie sur 0.0.0.0 que derriere une
# authentification, ce service n'en a aucune.
CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=4)"
