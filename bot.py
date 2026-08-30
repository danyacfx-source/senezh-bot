import asyncio
import logging

import discord
from discord.ext import commands

from config import PROXY_URL, TOKEN
import database as database
import webpanel as webpanel
from cogs.embeds import EmbedBuilder
from cogs.logging import LoggingCog
from cogs.tempvoice import TempVoice, TempChannelView
from cogs.tickets import (
    TicketCog,
    TicketCloseView,
    TicketClosedView,
)
from cogs.vacations import VacationCog, RequestVacationView

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

_proxy_url = PROXY_URL or ""
if _proxy_url.lower() in ("", "none", "system", "off", "0"):
    _proxy_url = ""

_bot_options = {}
if _proxy_url:
    _bot_options["proxy"] = _proxy_url

bot = commands.Bot(command_prefix="!", intents=intents, **_bot_options)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    data = interaction.data
    cid = data.get("custom_id") if isinstance(data, dict) else None
    print(
        f"[INTERACTION] type={interaction.type} custom_id={cid} user={interaction.user}",
        flush=True,
    )


@bot.event
async def on_ready():
    print(f"Бот запущен: {bot.user} (ID: {bot.user.id})", flush=True)
    for g in bot.guilds:
        print(f"СЕРВЕР: {g.name} | ID: {g.id}", flush=True)
        if not getattr(bot, "_commands_synced", False):
            try:
                synced = await bot.tree.sync()
                print(f"Синхронизировано команд: {len(synced)}", flush=True)
                for g in bot.guilds:
                    guild_synced = await bot.tree.sync(guild=g)
                    print(f"Синхронизировано команд для гильдии {g.name}: {len(guild_synced)}", flush=True)
            except Exception as e:
                print(f"Ошибка синхронизации команд: {e}", flush=True)
            bot._commands_synced = True
        store_views = getattr(bot._connection._view_store, "_views", {})
        print(f"[VIEWS] registered={list(store_views.get(None, {}).keys())}", flush=True)
        for item in store_views.get(None, {}).values():
            stopped = getattr(item.view, "_BaseView__stopped", "?")
            print(f"[VIEWS] item {item.custom_id} -> view={type(item.view).__name__} stopped={stopped is not None and not stopped.done()}", flush=True)


@bot.command()
async def ping(ctx: commands.Context):
    await ctx.send("Понг!")


@bot.command()
async def info(ctx: commands.Context):
    await ctx.send(f"Я — {bot.user.display_name}. Работаю, готов к командам.")


async def main():
    database.init_db()
    async with bot:
        bot.add_view(TempChannelView())
        bot.add_view(TicketCloseView())
        bot.add_view(TicketClosedView())
        bot.add_view(RequestVacationView())
        await bot.add_cog(EmbedBuilder(bot))
        await bot.add_cog(LoggingCog(bot))
        await bot.add_cog(TempVoice(bot))
        await bot.add_cog(TicketCog(bot))
        await bot.add_cog(VacationCog(bot))
        await webpanel.start(bot)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())