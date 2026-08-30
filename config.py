import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

_data_dir = os.environ.get("DATA_DIR", "").strip()
DATA_DIR = _data_dir or str(BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
if _data_dir:
    os.chdir(DATA_DIR)

TICKETS_FILE = os.path.join(DATA_DIR, "tickets.json")
TEMPVOICE_FILE = os.path.join(DATA_DIR, "tempvoice_owners.json")
VACATION_FILE = os.path.join(DATA_DIR, "vacations.json")
DB_FILE = os.path.join(DATA_DIR, "senezh.db")

_env_path = BASE_DIR / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_TOKEN") or ""
if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN/DISCORD_TOKEN не задан. Заполни .env")

PROXY_URL = os.environ.get("DISCORD_PROXY", "")

# Web panel (embed-constructor)
PANEL_HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PANEL_PORT = int(os.environ.get("PORT") or os.environ.get("PANEL_PORT") or "17890")
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "").strip()
PANEL_PUBLIC_URL = os.environ.get("PANEL_PUBLIC_URL", "").strip().rstrip("/")

TICKET_CATEGORY = 1543581803485462599
TICKET_STAFF_ROLES = [
    1543382942838169691,  # Генерал
    1543586076134739998,  # Майор
]
TICKET_TRANSCRIPT_CHANNEL = 1543591327898537994  # архив-заявок
TICKET_LOG_CHANNEL = 1543595825958101063  # логи тикетов
CLAN_ROLES = [1543391248931487764]  # Курсант
PROMOTION_ROLES: list[int] = []
COMMANDER_ROLES: list[int] = []

# Отпуска
VACATION_FILE = "vacations.json"
VACATION_ROLE_ID = 1543754015286763581  # роль отпускника (выдаётся при отпуске)
VACATION_LOG_CHANNEL = 1543753021111148584  # логи взятия/снятия/продления
VACATION_PANEL_CHANNEL = 1543549448859295774  # канал панели отпусков
VACATION_RETURN_CHANNEL = 1543549421982056498  # пинг пропавших (не вышедших из отпуска)
VACATION_PING_ROLES = [1543382942838169691, 1543586076134739998]  # Генерал, Майор