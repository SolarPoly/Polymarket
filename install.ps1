# Installation en une commande (Windows).
#
#   .\install.ps1
#
# Cree l'environnement virtuel, installe les dependances, prepare le .env,
# puis affiche la commande a lancer. Rejouable sans risque.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Venv = ".venv"
$Py = "$Venv\Scripts\python.exe"

function Say($msg) { Write-Host "  $msg" }
function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Die($msg) { Write-Host ""; Write-Host "ECHEC : $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "PolyTrade Engine - installation" -ForegroundColor White

# --- 1. Python --------------------------------------------------------------
Step "Recherche de Python 3.12 ou plus recent"

$launcher = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
$exe = if ($launcher) { "py" } elseif ($python) { "python" } else { $null }

if (-not $exe) {
    Die "Python est introuvable. Installe-le depuis https://www.python.org/downloads/ en cochant `"Add python.exe to PATH`"."
}

$version = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])"
Say "trouve : Python $version ($exe)"

$major, $minor = $version.Split('.')
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 12)) {
    Die "Python 3.12 minimum est requis, $version detecte."
}

# --- 2. Environnement virtuel ----------------------------------------------
Step "Preparation de l'environnement virtuel ($Venv)"

# Un venv cree sur un autre systeme est inutilisable ici : ce depot en a
# contenu un (macOS) pendant un temps, d'ou ce controle explicite.
if (Test-Path "$Venv\pyvenv.cfg") {
    $home_line = (Select-String -Path "$Venv\pyvenv.cfg" -Pattern '^home\s*=' -ErrorAction SilentlyContinue).Line
    if (-not (Test-Path $Py) -or ($home_line -and $home_line -notmatch '[A-Za-z]:\\')) {
        Warn "environnement existant incompatible avec ce systeme, recreation"
        Remove-Item -Recurse -Force $Venv
    }
}

if (-not (Test-Path $Py)) {
    & $exe -m venv $Venv
    if (-not (Test-Path $Py)) { Die "creation de l'environnement virtuel impossible." }
    Say "cree"
} else {
    Say "deja present, reutilise"
}

# --- 3. Dependances ---------------------------------------------------------
Step "Installation des dependances"
& $Py -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Die "mise a jour de pip impossible." }
& $Py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Die "installation des dependances impossible." }
Say "dependances d'execution installees"

if ($args -contains "--dev") {
    & $Py -m pip install -r requirements-dev.txt --quiet
    Say "outils de developpement installes"
}

# --- 4. Configuration -------------------------------------------------------
Step "Configuration"
if (Test-Path ".env") {
    Say ".env deja present, laisse tel quel"
} else {
    Copy-Item ".env.example" ".env"
    Say ".env cree depuis .env.example"
    Warn "POLYGON_PRIVATE_KEY doit etre renseignee avant d'utiliser les donnees reelles."
    Warn "Utilise un wallet dedie, alimente au strict necessaire. Le mode --demo n'en a pas besoin."
}

# --- 5. Verification --------------------------------------------------------
Step "Verification"
$check = & $Py -c "import py_clob_client, fastapi, uvicorn, dotenv; print('ok')" 2>&1
if ($check -notmatch "ok") { Die "les dependances ne s'importent pas : $check" }
Say "toutes les dependances s'importent"

# --- Fin --------------------------------------------------------------------
Write-Host ""
Write-Host "Installation terminee." -ForegroundColor Green
Write-Host ""
Write-Host "  Lancer l'interface (donnees simulees, aucune cle requise) :"
Write-Host "    .\$Py main.py serve --demo" -ForegroundColor White
Write-Host "    puis ouvrir http://127.0.0.1:8000"
Write-Host ""
Write-Host "  Autres commandes :"
Write-Host "    .\$Py main.py --help"
Write-Host ""
