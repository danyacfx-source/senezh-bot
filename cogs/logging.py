import asyncio
import logging
from datetime import datetime

import aiohttp
import discord
from discord.ext import commands

import config


def _moscow_time(now):
    moscow_ts = now.timestamp() + 3 * 3600
    dt = datetime.utcfromtimestamp(moscow_ts)
    is_today = dt.date() == datetime.utcfromtimestamp(now.timestamp()).date()
    time_display = (
        f"Сегодня, в {dt.strftime('%H:%M')}"
        if is_today
        else dt.strftime("%d.%m.%Y в %H:%M")
    )
    return time_display


class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            guild = member.guild
            if not guild:
                return

            channel = guild.get_channel(config.JOIN_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="👋 Участник присоединился",
                description=f"{member.mention} ({member})",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="ID", value=str(member.id), inline=True)
            embed.add_field(
                name="Аккаунт создан",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)
            embed.set_footer(text=f"Участников: {guild.member_count}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_join error: %s", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            guild = member.guild
            if not guild:
                return

            channel = guild.get_channel(config.JOIN_LOG_CHANNEL)
            if not channel:
                return

            moderator = None
            reason = "Не указана"

            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                    if entry.target and entry.target.id == member.id:
                        moderator = entry.user
                        reason = entry.reason or "Не указана"
                        break
            except discord.Forbidden:
                pass

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            if moderator:
                title = "Кик выдан"
                desc = f"{moderator.mention} ({moderator}) кикнул пользователя {member.mention} ({member})"
            else:
                title = "Участник покинул сервер"
                desc = f"{member.mention} ({member})"

            embed = discord.Embed(
                title=title,
                description=desc,
                color=discord.Color.orange(),
                timestamp=now,
            )

            embed.add_field(name="Причина", value=reason, inline=False)

            roles = [r.mention for r in member.roles if r != guild.default_role]
            embed.add_field(
                name="Роли", value=", ".join(roles) if roles else "@everyone", inline=False
            )

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"id участника: {member.id}•{time_display}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_remove error: %s", e)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        try:
            guild = member.guild
            if not guild:
                return

            log_channel = guild.get_channel(config.VOICE_LOG_CHANNEL)
            if not log_channel:
                return

            async def send_safe(embed):
                for attempt in range(3):
                    try:
                        await log_channel.send(embed=embed)
                        return
                    except (aiohttp.ClientError, discord.HTTPException) as e:
                        if attempt < 2:
                            await asyncio.sleep(5)
                        else:
                            logging.error("voice log не отправлен (3 попытки): %s", e)

            before_channel = before.channel
            after_channel = after.channel

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            def get_user_status(member):
                states = []
                if member.bot:
                    states.append("бот")
                if member.guild_permissions.administrator:
                    states.append("админ")
                return ", ".join(states) if states else "неизвестно"

            if not before_channel and after_channel:
                status = get_user_status(member)
                embed = discord.Embed(
                    title=f"Участник {member.display_name} (@{member.name}) зашёл в канал",
                    description=f"**{after_channel.name}** ({status})",
                    color=discord.Color.green(),
                    timestamp=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"id участника: {member.id}•{time_display}")
                await send_safe(embed)

            elif before_channel and not after_channel:
                status = get_user_status(member)
                embed = discord.Embed(
                    title=f"Участник {member.display_name} (@{member.name}) покинул канал",
                    description=f"**{before_channel.name}** ({status})",
                    color=discord.Color.red(),
                    timestamp=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"id участника: {member.id}•{time_display}")
                await send_safe(embed)

            elif before_channel and after_channel and before_channel.id != after_channel.id:
                status = get_user_status(member)
                embed = discord.Embed(
                    title=f"Участник {member.display_name} (@{member.name}) переместился",
                    description=(
                        f"**{before_channel.name}** → **{after_channel.name}** ({status})"
                    ),
                    color=discord.Color.blurple(),
                    timestamp=now,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"id участника: {member.id}•{time_display}")
                await send_safe(embed)

            elif before_channel and after_channel and before_channel.id == after_channel.id:
                changes = []
                if before.self_mute != after.self_mute:
                    changes.append(f"Self-Mute: {'Да' if after.self_mute else 'Нет'}")
                if before.self_deaf != after.self_deaf:
                    changes.append(f"Self-Deaf: {'Да' if after.self_deaf else 'Нет'}")
                if before.mute != after.mute:
                    changes.append(f"Мьют: {'Да' if after.mute else 'Нет'}")
                if before.deaf != after.deaf:
                    changes.append(f"Глух: {'Да' if after.deaf else 'Нет'}")
                if getattr(before, "stream", False) != getattr(after, "stream", False):
                    changes.append(f"Стрим: {'Да' if getattr(after, 'stream', False) else 'Нет'}")
                if getattr(before, "video", False) != getattr(after, "video", False):
                    changes.append(f"Видео: {'Да' if getattr(after, 'video', False) else 'Нет'}")

                if changes:
                    status = get_user_status(member)
                    embed = discord.Embed(
                        title=f"Участник {member.display_name} (@{member.name}) изменил состояние",
                        description=(
                            f"**{after_channel.name}** ({status})\n"
                            + "\n".join(changes)
                        ),
                        color=discord.Color.greyple(),
                        timestamp=now,
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"id участника: {member.id}•{time_display}")
                    await send_safe(embed)
        except Exception as e:
            logging.error("on_voice_state_update error: %s", e)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        try:
            if message.author.bot:
                return

            channel = self.bot.get_channel(config.MESSAGE_LOG_CHANNEL)
            if not channel:
                return

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            content = message.content[:1900] if message.content else "_Пусто_"
            if message.attachments:
                attachments = "\n".join(f"• {a.filename}" for a in message.attachments[:5])
                content += f"\n\n**Вложения:**\n{attachments}"

            embed = discord.Embed(
                title="Сообщение было удалено",
                description=f"**Содержание:**\n{content}",
                color=discord.Color.red(),
                timestamp=now,
            )
            embed.add_field(
                name="Автор",
                value=f"{message.author.display_name} ({message.author})",
                inline=True,
            )
            embed.add_field(
                name="Канал",
                value=f"{message.channel.mention} ({message.channel})",
                inline=True,
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            embed.set_footer(text=f"id сообщения: {message.id}•{time_display}")

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_message_delete error: %s", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        try:
            if before.author.bot:
                return
            if before.content == after.content:
                return

            channel = self.bot.get_channel(config.MESSAGE_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="✏️ Сообщение изменено",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Автор", value=f"{before.author} ({before.author.id})", inline=True)
            embed.add_field(name="Канал", value=before.channel.mention, inline=True)

            old_content = before.content[:1024] if before.content else "*Пусто*"
            new_content = after.content[:1024] if after.content else "*Пусто*"
            embed.add_field(name="Было", value=old_content, inline=False)
            embed.add_field(name="Стало", value=new_content, inline=False)

            embed.set_thumbnail(url=before.author.display_avatar.url)
            embed.set_footer(text=f"ID сообщения: {before.id}")
            embed.add_field(
                name="Ссылка",
                value=f"[Перейти]({before.jump_url})",
                inline=True,
            )

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_message_edit error: %s", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoggingCog(bot))