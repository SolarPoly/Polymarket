#!/usr/bin/env bash
# Installation en une commande (Linux, macOS).
#
#   ./install.sh          installation standard
#   ./install.sh --dev    avec les outils de developpement
#
# Rejouable sans risque.

set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"

say()  { printf '  %s\n' "$1"; }
step() { printf '\n==> %s\n' "$1"; }
warn() { printf '  ! %s\n' "$1"; }
die()  { printf '\nECHEC : %s\n' "$1" >&2; exit 1; }

printf '\nPolyTrade Engine - installation\n'

# --- 1. Python --------------------------------------------------------------
step "Recherche de Python 3.12 ou plus recent"

EXE=""
for candidate in python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    major=${version%%.*}
    minor=${version##*.}
    if [ "$major" -eq 3 ] && [ "$minor" -ge 12 ]; then
      EXE="$candidate"
      break
    fi
  fi
done

[ -n "$EXE" ] || die "Python 3.12 minimum est requis et n'a pas ete trouve."
say "trouve : Python $("$EXE" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])') ($EXE)"

# --- 2. Environnement virtuel ----------------------------------------------
step "Preparation de l'environnement virtuel ($VENV)"

# Un venv cree sur un autre systeme est inutilisable : ce depot en a contenu
# un (macOS, pousse depuis Windows) pendant un temps, d'ou ce controle.
if [ -f "$VENV/pyvenv.cfg" ] && [ ! -x "$PY" ]; then
  warn "environnement existant incompatible avec ce systeme, recreation"
  rm -rf "$VENV"
fi

if [ ! -x "$PY" ]; then
  "$EXE" -m venv "$VENV"
  [ -x "$PY" ] || die "creation de l'environnement virtuel impossible."
  say "cree"
else
  say "deja present, reutilise"
fi

# --- 3. Dependances ---------------------------------------------------------
step "Installation des dependances"
"$PY" -m pip install --upgrade pip --quiet || die "mise a jour de pip impossible."
"$PY" -m pip install -r requirements.txt --quiet || die "installation des dependances impossible."
say "dependances d'execution installees"

for arg in "$@"; do
  if [ "$arg" = "--dev" ]; then
    "$PY" -m pip install -r requirements-dev.txt --quiet
    say "outils de developpement installes"
  fi
done

# --- 4. Configuration -------------------------------------------------------
step "Configuration"
if [ -f .env ]; then
  say ".env deja present, laisse tel quel"
else
  cp .env.example .env
  say ".env cree depuis .env.example"
  warn "POLYGON_PRIVATE_KEY doit etre renseignee avant d'utiliser les donnees reelles."
  warn "Utilise un wallet dedie, alimente au strict necessaire. Le mode --demo n'en a pas besoin."
fi

# --- 5. Verification --------------------------------------------------------
step "Verification"
"$PY" -c "import py_clob_client, fastapi, uvicorn, dotenv" \
  || die "les dependances ne s'importent pas."
say "toutes les dependances s'importent"

# --- Fin --------------------------------------------------------------------
cat <<EOF

Installation terminee.

  Lancer l'interface (donnees simulees, aucune cle requise) :
    $PY main.py serve --demo
    puis ouvrir http://127.0.0.1:8000

  Autres commandes :
    $PY main.py --help

EOF
