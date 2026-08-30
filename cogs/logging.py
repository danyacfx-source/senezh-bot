import asyncio
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import aiohttp
import discord
from discord.ext import commands, tasks

import config
import database as db


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
        self._last_backup_key = None

    async def cog_load(self):
        self.daily_backup.start()

    async def _run_backup(self):
        try:
            channel = self.bot.get_channel(config.BACKUP_CHANNEL)
            if not channel:
                logging.error("backup: канал не найден: %s", config.BACKUP_CHANNEL)
                return

            now = datetime.utcnow() + timedelta(hours=3)
            name = f"senezh_backup_{now.strftime('%Y-%m-%d_%H-%M')}.db"

            tmp_path = os.path.join(tempfile.gettempdir(), name)
            src = db.get_conn()
            dst = sqlite3.connect(tmp_path)
            try:
                src.backup(dst)
            finally:
                dst.close()

            embed = discord.Embed(
                title="💾 Ежедневный бэкап",
                description=f"Файл: `{name}`\nРазмер: **{os.path.getsize(tmp_path)} байт**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )

            await channel.send(embed=embed, file=discord.File(tmp_path, filename=name))
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        except Exception as e:
            logging.error("backup error: %s", e, exc_info=True)

    @tasks.loop(minutes=1)
    async def daily_backup(self):
        now = datetime.utcnow()
        if now.hour != 0 or now.minute > 2:
            return

        key = f"{now.year}-{now.month}-{now.day}"
        if self._last_backup_key == key:
            return
        self._last_backup_key = key

        await self._run_backup()

    @daily_backup.before_loop
    async def before_daily_backup(self):
        await self.bot.wait_until_ready()

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
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            if before.guild is None:
                return

            guild = before.guild

            old_roles = set(r.id for r in before.roles)
            new_roles = set(r.id for r in after.roles)
            added_roles = new_roles - old_roles
            removed_roles = old_roles - new_roles

            if not added_roles and not removed_roles:
                return

            role_channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not role_channel:
                return

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.member_role_update):
                    if entry.target and entry.target.id == after.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title=f"Роли участника {after.display_name} (@{after.name}) были изменены",
                color=discord.Color.blurple(),
                timestamp=now,
            )

            if added_roles:
                role_names = [f"<@&{rid}>" for rid in added_roles]
                embed.add_field(name="➕ Добавлены роли", value=", ".join(role_names), inline=False)

            if removed_roles:
                role_names = [f"<@&{rid}>" for rid in removed_roles]
                embed.add_field(name="➖ Удалены роли", value=", ".join(role_names), inline=False)

            embed.add_field(
                name="Кто изменил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )

            embed.set_thumbnail(url=after.display_avatar.url)
            embed.set_footer(text=f"id участника: {after.id}·{time_display}")

            await role_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_member_update error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        try:
            guild = role.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="🔵 Роль создана",
                description=f"{role.mention} ({role.name})",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="ID", value=str(role.id), inline=True)
            embed.add_field(name="Цвет", value=str(role.color), inline=True)
            embed.add_field(name="Отображаемая отдельно", value="Да" if role.hoist else "Нет", inline=True)

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_role_create error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        try:
            guild = role.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            embed = discord.Embed(
                title="⚫ Роль удалена",
                description=f"**{role.name}**",
                color=discord.Color.dark_grey(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="ID", value=str(role.id), inline=True)
            embed.add_field(name="Цвет", value=str(role.color), inline=True)
            embed.add_field(name="Участников с ролью", value=str(len(role.members)), inline=True)

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_role_delete error: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        try:
            guild = after.guild
            channel = guild.get_channel(config.ROLE_LOG_CHANNEL)
            if not channel:
                return

            changes = []
            if before.name != after.name:
                changes.append(f"**Имя роли изменено:** `{before.name}` → `{after.name}`")
            if before.color != after.color:
                changes.append(f"**Цвет изменён:** `{before.color}` → `{after.color}`")
            if before.hoist != after.hoist:
                val = "Да" if after.hoist else "Нет"
                changes.append(f"**Отображаемая отдельно:** {val}")
            if before.mentionable != after.mentionable:
                val = "Да" if after.mentionable else "Нет"
                changes.append(f"**Упоминаемая:** {val}")

            if not changes:
                return

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.role_update):
                    if entry.target and entry.target.id == after.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title=f"Роль {after.mention} была изменена",
                description="\n".join(changes),
                color=discord.Color.purple(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто изменил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            if moderator:
                embed.set_footer(text=f"id участника: {moderator.id}·{time_display}")
            else:
                embed.set_footer(text=time_display)

            await channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_role_update error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        try:
            guild = channel.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_create):
                    if entry.target and entry.target.id == channel.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            channel_type = (
                "text"
                if isinstance(channel, discord.TextChannel)
                else "voice"
                if isinstance(channel, discord.VoiceChannel)
                else "category"
                if isinstance(channel, discord.CategoryChannel)
                else "announcement"
                if isinstance(channel, discord.ForumChannel)
                else str(channel.type)
            )

            embed = discord.Embed(
                title=f"Канал {channel.name} ({channel.id}) был создан",
                color=discord.Color.green(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто создал",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            embed.add_field(name="Тип канала", value=channel_type, inline=True)

            if moderator:
                embed.set_footer(text=f"ID модератора: {moderator.id}·{time_display}")
            else:
                embed.set_footer(text=time_display)

            await log_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_channel_create error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            guild = channel.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
                    if entry.target and entry.target.id == channel.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            channel_type = (
                "text"
                if isinstance(channel, discord.TextChannel)
                else "voice"
                if isinstance(channel, discord.VoiceChannel)
                else "category"
                if isinstance(channel, discord.CategoryChannel)
                else "announcement"
                if isinstance(channel, discord.ForumChannel)
                else str(channel.type)
            )

            embed = discord.Embed(
                title=f"Канал {channel.name} ({channel.id}) был удалён",
                color=discord.Color.red(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто удалил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            embed.add_field(name="Тип канала", value=channel_type, inline=True)

            if moderator:
                embed.set_footer(text=f"ID модератора: {moderator.id}·{time_display}")
            else:
                embed.set_footer(text=time_display)

            await log_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_channel_delete error: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        try:
            guild = after.guild
            log_channel = guild.get_channel(config.CHANNEL_LOG_CHANNEL)
            if not log_channel:
                return

            now = discord.utils.utcnow()
            time_display = _moscow_time(now)

            moderator = None
            try:
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_update):
                    if entry.target and entry.target.id == after.id:
                        moderator = entry.user
                        break
            except discord.Forbidden:
                pass

            changes = []
            if before.name != after.name:
                changes.append(f"**Название:** `{before.name}` → `{after.name}`")
            if before.category != after.category:
                old_cat = before.category.name if before.category else "Нет"
                new_cat = after.category.name if after.category else "Нет"
                changes.append(f"**Категория:** `{old_cat}` → `{new_cat}`")
            if hasattr(before, "topic") and before.topic != after.topic:
                old_topic = before.topic or "Нет"
                new_topic = after.topic or "Нет"
                changes.append(f"**Топик:** `{old_topic[:50]}` → `{new_topic[:50]}`")
            if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
                changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")
            if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
                changes.append(
                    f"**Слоумод:** `{before.slowmode_delay}с` → `{after.slowmode_delay}с`"
                )
            if hasattr(before, "overwrites") and dict(before.overwrites) != dict(after.overwrites):
                changes.append("**Разрешения изменены**")

            if before.name != after.name and isinstance(after, discord.VoiceChannel):
                changes.append(f"**Войс-канал переименован:** `{before.name}` → `{after.name}`")

            if not changes:
                return

            embed = discord.Embed(
                title=f"Канал {after.name} ({after.id}) был обновлён",
                color=discord.Color.gold(),
                timestamp=now,
            )
            embed.add_field(
                name="Кто обновил",
                value=f"{moderator.mention} {moderator}" if moderator else "Неизвестно",
                inline=True,
            )
            embed.add_field(name="Изменения", value="\n".join(changes), inline=False)

            if moderator:
                embed.set_footer(text=f"ID модератора: {moderator.id}·{time_display}")
            else:
                embed.set_footer(text=time_display)

            await log_channel.send(embed=embed)
        except Exception as e:
            logging.error("on_guild_channel_update error: %s", e)

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