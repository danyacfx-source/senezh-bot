import json
import logging
import os
import sqlite3
import threading

import config

log = logging.getLogger("database")

_lock = threading.RLock()
_conn = None


def get_conn():
    global _conn
    if _conn is None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(config.DB_FILE, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


_TICKET_COLS = [
    "user_id", "channel_id", "type", "status", "created_at", "guild_id",
    "closed_at", "closed_by", "transcript",
    "approved_by", "approved_at", "rejected_by", "rejected_at",
]


def init_db():
    with _lock:
        conn = get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id  TEXT PRIMARY KEY,
                user_id     INTEGER DEFAULT 0,
                type        TEXT DEFAULT '',
                status      TEXT DEFAULT 'open',
                created_at  TEXT DEFAULT '',
                guild_id    INTEGER DEFAULT 0,
                closed_at   TEXT DEFAULT '',
                closed_by   INTEGER DEFAULT 0,
                transcript  TEXT DEFAULT '',
                approved_by INTEGER DEFAULT 0,
                approved_at TEXT DEFAULT '',
                rejected_by INTEGER DEFAULT 0,
                rejected_at TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS tempvoice (
                channel_id INTEGER PRIMARY KEY,
                owner_id   INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vacations (
                user_key  TEXT PRIMARY KEY,
                user_name TEXT DEFAULT '',
                periods   TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS panel (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        conn.commit()
        _migrate_from_json()


def _migrate_from_json():
    conn = get_conn()

    if not conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]:
        if os.path.exists(config.TICKETS_FILE):
            try:
                with open(config.TICKETS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                for cid, t in (data or {}).items():
                    if not isinstance(t, dict) or str(cid).startswith("_"):
                        continue
                    save_ticket({
                        "channel_id": str(cid),
                        "user_id": t.get("user_id", 0),
                        "type": t.get("type", ""),
                        "status": t.get("status", "open"),
                        "created_at": t.get("created_at", ""),
                        "guild_id": t.get("guild_id", 0),
                        "closed_at": t.get("closed_at", ""),
                        "closed_by": t.get("closed_by", 0),
                        "transcript": t.get("transcript", ""),
                        "approved_by": t.get("approved_by", 0),
                        "approved_at": t.get("approved_at", ""),
                        "rejected_by": t.get("rejected_by", 0),
                        "rejected_at": t.get("rejected_at", ""),
                    })
                log.info("Мигрировано тикетов из %s", config.TICKETS_FILE)
            except Exception as e:
                log.warning("Не удалось мигрировать тикеты из JSON: %s", e)
            else:
                try:
                    os.replace(config.TICKETS_FILE, config.TICKETS_FILE + ".bak")
                except OSError:
                    pass

    if not conn.execute("SELECT COUNT(*) FROM tempvoice").fetchone()[0]:
        if os.path.exists(config.TEMPVOICE_FILE):
            try:
                with open(config.TEMPVOICE_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                owners = {int(k): int(v) for k, v in (data or {}).items()}
                if owners:
                    save_tempvoice_owners(owners)
                log.info("Мигрированы владельцы темп-каналов из %s", config.TEMPVOICE_FILE)
            except Exception as e:
                log.warning("Не удалось мигрировать tempvoice из JSON: %s", e)
            else:
                try:
                    os.replace(config.TEMPVOICE_FILE, config.TEMPVOICE_FILE + ".bak")
                except OSError:
                    pass

    if not conn.execute("SELECT COUNT(*) FROM vacations").fetchone()[0]:
        if os.path.exists(config.VACATION_FILE):
            try:
                with open(config.VACATION_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                panel_info = data.pop("__panel__", None)
                for uid, v in (data or {}).items():
                    if not isinstance(v, dict):
                        continue
                    save_vacation(str(uid), v.get("user_name", ""), v.get("periods", []))
                if panel_info:
                    save_panel("vacation_panel", panel_info)
                log.info("Мигрированы отпуска из %s", config.VACATION_FILE)
            except Exception as e:
                log.warning("Не удалось мигрировать отпуска из JSON: %s", e)
            else:
                try:
                    os.replace(config.VACATION_FILE, config.VACATION_FILE + ".bak")
                except OSError:
                    pass


def save_ticket(ticket: dict):
    with _lock:
        conn = get_conn()
        cid = str(ticket.get("channel_id", ""))
        conn.execute(
            """
            INSERT OR REPLACE INTO tickets
            (channel_id, user_id, type, status, created_at, guild_id,
             closed_at, closed_by, transcript,
             approved_by, approved_at, rejected_by, rejected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                int(ticket.get("user_id", 0) or 0),
                ticket.get("type", ""),
                ticket.get("status", "open"),
                ticket.get("created_at", ""),
                int(ticket.get("guild_id", 0) or 0),
                ticket.get("closed_at", ""),
                int(ticket.get("closed_by", 0) or 0),
                ticket.get("transcript", ""),
                int(ticket.get("approved_by", 0) or 0),
                ticket.get("approved_at", ""),
                int(ticket.get("rejected_by", 0) or 0),
                ticket.get("rejected_at", ""),
            ),
        )
        conn.commit()


def delete_ticket(channel_id):
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM tickets WHERE channel_id = ?", (str(channel_id),))
        conn.commit()


def load_tickets() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tickets").fetchall()
    result = {}
    for r in rows:
        result[r["channel_id"]] = {k: r[k] for k in _TICKET_COLS}
        result[r["channel_id"]]["channel_id"] = r["channel_id"]
    return result


def load_tempvoice_owners() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT channel_id, owner_id FROM tempvoice").fetchall()
    return {r["channel_id"]: r["owner_id"] for r in rows}


def save_tempvoice_owners(owners: dict):
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM tempvoice")
        conn.executemany(
            "INSERT INTO tempvoice (channel_id, owner_id) VALUES (?, ?)",
            [(int(k), int(v)) for k, v in owners.items()],
        )
        conn.commit()


def load_vacations() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM vacations").fetchall()
    result = {}
    for r in rows:
        try:
            periods = json.loads(r["periods"] or "[]")
        except ValueError:
            periods = []
        result[r["user_key"]] = {
            "user_name": r["user_name"] or "",
            "periods": periods,
        }
    return result


def save_vacation(user_key: str, user_name: str, periods: list):
    with _lock:
        conn = get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO vacations (user_key, user_name, periods)
            VALUES (?, ?, ?)
            """,
            (user_key, user_name, json.dumps(periods, ensure_ascii=False)),
        )
        conn.commit()


def delete_vacation(user_key: str):
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM vacations WHERE user_key = ?", (user_key,))
        conn.commit()


def load_panel(key: str):
    conn = get_conn()
    row = conn.execute("SELECT value FROM panel WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except ValueError:
        return None


def save_panel(key: str, value):
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO panel (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()