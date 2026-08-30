import json
import logging
import os
import secrets
from pathlib import Path

import aiohttp
import discord
from aiohttp import web

import config

log = logging.getLogger("webpanel")

HOST = config.PANEL_HOST
PORT = config.PANEL_PORT
PASSWORD = config.PANEL_PASSWORD
PUBLIC_URL = config.PANEL_PUBLIC_URL
ALLOWED_ORIGINS = {
    f"http://{HOST}:{PORT}",
    f"http://localhost:{PORT}",
}
if PUBLIC_URL:
    ALLOWED_ORIGINS.add(PUBLIC_URL)
TOKEN = secrets.token_urlsafe(16)
INDEX_PATH = Path(__file__).resolve().parent / "webpanel" / "index.html"

bot = None
aiohttp_timeout = aiohttp.ClientTimeout(total=25)

COLOR_NAMES = {
    "red": 0xE74C3C, "orange": 0xE67E22, "yellow": 0xF1C40F,
    "green": 0x2ECC71, "teal": 0x1ABC9C, "blue": 0x3498DB,
    "darkblue": 0x206694, "purple": 0x9B59B6, "pink": 0xE91E63,
    "white": 0xFFFFFF, "gray": 0x95A5A6, "dark": 0x2C2F33,
}


def _require_token(request: web.Request):
    origin = request.headers.get("Origin")
    if origin:
        oh = (origin.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]).lower()
        host = (request.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if oh != host and origin not in ALLOWED_ORIGINS:
            raise web.HTTPForbidden(text="bad origin")
    if request.headers.get("X-Panel-Token") != TOKEN:
        raise web.HTTPUnauthorized(text="bad token")


def _main_guild():
    for g in bot.guilds:
        return g
    return None


async def h_index(request: web.Request):
    html = INDEX_PATH.read_text(encoding="utf-8")
    if PASSWORD:
        html = html.replace("__PANEL_TOKEN__", "")
        html = html.replace("__PANEL_LOGIN__", "true")
    else:
        html = html.replace("__PANEL_TOKEN__", TOKEN)
        html = html.replace("__PANEL_LOGIN__", "false")
    return web.Response(text=html, content_type="text/html")


async def h_login(request: web.Request):
    data = await request.json()
    password = data.get("password") or ""
    if PASSWORD and password == PASSWORD:
        return web.json_response({"token": TOKEN})
    return web.json_response({"error": "wrong password"}, status=401)


async def h_status(request: web.Request):
    guild = _main_guild()
    return web.json_response(
        {
            "ok": True,
            "bot_online": bot.is_ready(),
            "bot_name": bot.user.name if bot.is_ready() else None,
            "guild_id": str(guild.id) if guild else None,
            "guild_name": guild.name if guild else None,
        }
    )


async def h_channels(request: web.Request):
    _require_token(request)
    guild_id = request.query.get("guild_id")
    guild = bot.get_guild(int(guild_id) if guild_id else 0) or _main_guild()
    if not guild:
        return web.json_response({"error": "guild not found"}, status=404)
    channels = []
    for c in guild.channels:
        if isinstance(c, discord.TextChannel) and c.permissions_for(guild.me).send_messages:
            channels.append(
                {
                    "id": str(c.id),
                    "name": c.name,
                    "category": c.category.name if c.category else None,
                    "nsfw": c.nsfw,
                }
            )
    channels.sort(key=lambda c: (c["category"] or "", c["name"]))
    return web.json_response({"ok": True, "channels": channels})


async def _webhook_request(method: str, url: str, payload=None):
    proxy = config.PROXY_URL or None
    async with aiohttp.ClientSession(timeout=aiohttp_timeout) as session:
        async with session.request(method, url, json=payload, proxy=proxy) as r:
            text = await r.text()
            try:
                body = json.loads(text) if text else None
            except Exception:
                body = text
            return r.status, body


async def h_webhook_fetch(request: web.Request):
    _require_token(request)
    data = await request.json()
    webhook_url = (data.get("webhook_url") or "").strip()
    message_id = (data.get("message_id") or "").strip()
    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return web.json_response({"error": "invalid webhook url"}, status=400)
    if not message_id:
        return web.json_response({"error": "message_id required"}, status=400)
    try:
        status, body = await _webhook_request("GET", f"{webhook_url}/messages/{message_id}")
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)
    if status >= 400:
        return web.json_response({"ok": False, "status": status, "data": body}, status=status)
    return web.json_response({"ok": True, "data": body})


async def h_webhook_send(request: web.Request):
    _require_token(request)
    data = await request.json()
    webhook_url = (data.get("webhook_url") or "").strip()
    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return web.json_response({"error": "invalid webhook url"}, status=400)
    payload = {"content": data.get("content") or "", "embeds": data.get("embeds") or []}
    if not (payload["content"].strip() or payload["embeds"]):
        return web.json_response({"error": "empty message"}, status=400)
    try:
        status, body = await _webhook_request("POST", webhook_url + "?wait=true", payload)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)
    if status >= 400:
        return web.json_response({"ok": False, "status": status, "data": body}, status=status)
    return web.json_response({"ok": True, "data": body})


async def h_webhook_edit(request: web.Request):
    _require_token(request)
    data = await request.json()
    webhook_url = (data.get("webhook_url") or "").strip()
    message_id = (data.get("message_id") or "").strip()
    if not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return web.json_response({"error": "invalid webhook url"}, status=400)
    if not message_id:
        return web.json_response({"error": "message_id required"}, status=400)
    payload = {"content": data.get("content") or "", "embeds": data.get("embeds") or []}
    if not (payload["content"].strip() or payload["embeds"]):
        return web.json_response({"error": "empty message"}, status=400)
    try:
        status, body = await _webhook_request("PATCH", f"{webhook_url}/messages/{message_id}", payload)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=502)
    if status >= 400:
        return web.json_response({"ok": False, "status": status, "data": body}, status=status)
    return web.json_response({"ok": True, "data": body})


def _embeds_from_client(data: dict):
    raw = data.get("embeds") or []
    out = []
    for e in raw[:10]:
        if isinstance(e, dict) and (e.get("title") or e.get("description") or e.get("fields")):
            out.append(discord.Embed.from_dict(e))
    return out


async def h_bot_send(request: web.Request):
    _require_token(request)
    data = await request.json()
    channel = bot.get_channel(int(data.get("channel_id") or 0))
    if channel is None:
        return web.json_response({"error": "channel not found"}, status=404)
    embeds = _embeds_from_client(data)
    content = data.get("content") or ""
    if not (content.strip() or embeds):
        return web.json_response({"error": "empty message"}, status=400)
    try:
        msg = await channel.send(
            content=content if content.strip() else None,
            embeds=embeds if embeds else None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True, "message_id": str(msg.id)})


async def h_bot_edit(request: web.Request):
    _require_token(request)
    data = await request.json()
    channel = bot.get_channel(int(data.get("channel_id") or 0))
    message_id = int(data.get("message_id") or 0)
    if channel is None:
        return web.json_response({"error": "channel not found"}, status=404)
    if not message_id:
        return web.json_response({"error": "message_id required"}, status=400)
    embeds = _embeds_from_client(data)
    content = data.get("content") or ""
    if not (content.strip() or embeds):
        return web.json_response({"error": "empty message"}, status=400)
    try:
        msg = await channel.get_partial_message(message_id).fetch()
        await msg.edit(
            content=content if content.strip() else None,
            embeds=embeds if embeds else None,
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True, "message_id": str(msg.id)})


async def h_bot_fetch(request: web.Request):
    _require_token(request)
    data = await request.json()
    channel = bot.get_channel(int(data.get("channel_id") or 0))
    message_id = int(data.get("message_id") or 0)
    if channel is None:
        return web.json_response({"error": "channel not found"}, status=404)
    if not message_id:
        return web.json_response({"error": "message_id required"}, status=400)
    try:
        msg = await channel.get_partial_message(message_id).fetch()
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response(
        {
            "ok": True,
            "data": {
                "content": msg.content or "",
                "embeds": [e.to_dict() for e in msg.embeds],
                "message_id": str(msg.id),
            },
        }
    )


async def start(bot_client):
    global bot
    bot = bot_client
    app = web.Application()
    app["panel_token"] = TOKEN
    app.router.add_get("/", h_index)
    app.router.add_get("/admin/embed-constructor", h_index)
    app.router.add_post("/api/login", h_login)
    app.router.add_get("/api/status", h_status)
    app.router.add_get("/api/bot/channels", h_channels)
    app.router.add_post("/api/webhook/send", h_webhook_send)
    app.router.add_post("/api/webhook/edit", h_webhook_edit)
    app.router.add_post("/api/webhook/fetch", h_webhook_fetch)
    app.router.add_post("/api/bot/send", h_bot_send)
    app.router.add_post("/api/bot/edit", h_bot_edit)
    app.router.add_post("/api/bot/fetch", h_bot_fetch)
    runner = web.AppRunner(app)
    await runner.setup()
    ports = [PORT]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        ports.append(80)
    for p in dict.fromkeys(ports):
        try:
            site = web.TCPSite(runner, HOST, p)
            await site.start()
            log.info("Панель запущена: http://%s:%s/admin/embed-constructor", HOST, p)
            print(f"[WEBPANEL] http://{HOST}:{p}/admin/embed-constructor", flush=True)
        except Exception as e:
            log.warning("Не удалось занять порт %s: %s", p, e)
    bot._webpanel_runner = runner
    return runner