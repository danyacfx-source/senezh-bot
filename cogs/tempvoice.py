from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import database as db

TRIGGER_CHANNEL_ID = 1543552319663374376
NEW_CHANNEL_NAME = "Клановый"

temp_channel_owners: dict[int, int] = {}
_channel_locks: dict[int, asyncio.Lock] = {}


def _load_owners():
    return db.load_tempvoice_owners()


def _save_owners():
    db.save_tempvoice_owners(temp_channel_owners)


def _channel_lock(channel_id: int) -> asyncio.Lock:
    lock = _channel_locks.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        _channel_locks[channel_id] = lock
    return lock


def _is_managed(channel: discord.VoiceChannel | None) -> bool:
    return channel is not None and channel.id in temp_channel_owners


def _is_owner(interaction: discord.Interaction, vc: discord.VoiceChannel) -> bool:
    return temp_channel_owners.get(vc.id) == interaction.user.id


class TempChannelKickModal(discord.ui.Modal, title="Выгнать участника"):
    target = discord.ui.TextInput(label="ID или упоминание участника", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "Вы не в голосовом канале.", ephemeral=True
            )
        vc = interaction.user.voice.channel
        if not _is_managed(vc):
            return await interaction.response.send_message(
                "Нельзя управлять этим каналом.", ephemeral=True
            )
        if not _is_owner(interaction, vc):
            return await interaction.response.send_message(
                "Только владелец канала может выгонять.", ephemeral=True
            )
        raw = self.target.value.strip()
        uid = raw.strip("<@!>")
        try:
            uid = int(uid)
        except ValueError:
            return await interaction.response.send_message(
                "Укажите ID участника.", ephemeral=True
            )
        member = interaction.guild.get_member(uid)
        if not member:
            try:
                member = await interaction.guild.fetch_member(uid)
            except discord.errors.NotFound:
                member = None
            except discord.errors.Forbidden:
                member = None
        if not member:
            return await interaction.response.send_message(
                "Участник не найден.", ephemeral=True
            )
        if member.voice and member.voice.channel and member.voice.channel.id == vc.id:
            await member.move_to(None, reason="Выгнан из кланового канала")
            await interaction.response.send_message(
                f"✅ {member.mention} выгнан.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Участник не в вашем канале.", ephemeral=True
            )


class TempChannelRenameModal(discord.ui.Modal, title="Переименовать канал"):
    new_name = discord.ui.TextInput(label="Новое название", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "Вы не в голосовом канале.", ephemeral=True
            )
        vc = interaction.user.voice.channel
        if not _is_managed(vc):
            return await interaction.response.send_message(
                "Нельзя управлять этим каналом.", ephemeral=True
            )
        if not _is_owner(interaction, vc):
            return await interaction.response.send_message(
                "Только владелец канала может переименовывать.", ephemeral=True
            )
        old_name = vc.name
        await vc.edit(name=self.new_name.value, reason="Переименован владельцем")
        await interaction.response.send_message(
            f"✅ Канал переименован: `{old_name}` → `{self.new_name.value}`",
            ephemeral=True,
        )


class TempChannelLimitModal(discord.ui.Modal, title="Лимит участников"):
    limit = discord.ui.TextInput(label="Лимит (0 = без лимита, макс. 99)", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "Вы не в голосовом канале.", ephemeral=True
            )
        vc = interaction.user.voice.channel
        if not _is_managed(vc):
            return await interaction.response.send_message(
                "Нельзя управлять этим каналом.", ephemeral=True
            )
        if not _is_owner(interaction, vc):
            return await interaction.response.send_message(
                "Только владелец канала может менять лимит.", ephemeral=True
            )
        try:
            n = int(self.limit.value)
        except ValueError:
            return await interaction.response.send_message("Введите число.", ephemeral=True)
        if n < 0 or n > 99:
            return await interaction.response.send_message(
                "Лимит должен быть от 0 до 99.", ephemeral=True
            )
        await vc.edit(user_limit=n, reason="Лимит изменён владельцем")
        text = "✅ Лимит снят." if n == 0 else f"✅ Лимит установлен: **{n}** участников."
        await interaction.response.send_message(text, ephemeral=True)


class TempChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.danger, custom_id="senezh_temp_vc_lock")
    async def lock_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "Вы не в голосовом канале.", ephemeral=True
            )
        vc = interaction.user.voice.channel
        if not _is_managed(vc):
            return await interaction.response.send_message(
                "Нельзя управлять этим каналом.", ephemeral=True
            )
        if not _is_owner(interaction, vc):
            return await interaction.response.send_message(
                "Только владелец канала может закрывать/открывать.", ephemeral=True
            )
        everyone = interaction.guild.default_role
        current = vc.overwrites_for(everyone)
        if current.connect is False:
            current.connect = None
            await vc.set_overwrite(everyone, overwrite=current, reason="Канал открыт")
            button.label = "🔒 Закрыть"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("✅ Канал открыт.", ephemeral=True)
        else:
            current.connect = False
            await vc.set_overwrite(everyone, overwrite=current, reason="Канал закрыт")
            button.label = "🔓 Открыть"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("✅ Канал закрыт.", ephemeral=True)

    @discord.ui.button(label="👢 Выгнать", style=discord.ButtonStyle.secondary, custom_id="senezh_temp_vc_kick")
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempChannelKickModal())

    @discord.ui.button(label="✏️ Название", style=discord.ButtonStyle.primary, custom_id="senezh_temp_vc_rename")
    async def rename_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempChannelRenameModal())

    @discord.ui.button(label="👥 Лимит", style=discord.ButtonStyle.success, custom_id="senezh_temp_vc_limit")
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TempChannelLimitModal())

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        logging.error("Ошибка в TempChannelView: %s", error, exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Произошла ошибка.", ephemeral=True)
            else:
                await interaction.response.send_message("Произошла ошибка.", ephemeral=True)
        except Exception:
            pass


TEMP_GUILD_ID = 1386368131500609546


class TempVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._started = False
        global temp_channel_owners
        temp_channel_owners = _load_owners()

    def _managed_channels(self, guild: discord.Guild) -> list[discord.VoiceChannel]:
        result = []
        for ch in guild.voice_channels:
            if ch.id in temp_channel_owners:
                result.append(ch)
        return result

    @tasks.loop(seconds=60)
    async def cleanup_loop(self):
        for guild in self.bot.guilds:
            for vc in self._managed_channels(guild):
                if not [m for m in vc.members if not m.bot]:
                    await self._delete_channel(vc, reason="Периодическая уборка")

    async def _delete_channel(self, vc: discord.VoiceChannel, reason: str):
        async with _channel_lock(vc.id):
            try:
                temp_channel_owners.pop(vc.id, None)
                await vc.delete(reason=reason)
                _save_owners()
                logging.info("Удалён клановый канал %s", vc.name)
            except discord.NotFound:
                temp_channel_owners.pop(vc.id, None)
                _save_owners()
            except Exception as e:
                logging.error("Ошибка удаления канала %s: %s", vc.name, e)

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._started:
            self._started = True
            self.cleanup_loop.start()
        for guild in self.bot.guilds:
            stale = [cid for cid in temp_channel_owners if guild.get_channel(cid) is None]
            for cid in stale:
                temp_channel_owners.pop(cid, None)
            if stale:
                _save_owners()
            for vc in self._managed_channels(guild):
                if not [m for m in vc.members if not m.bot]:
                    await self._delete_channel(vc, reason="Очистка при запуске")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return

        if after.channel and after.channel.id == TRIGGER_CHANNEL_ID:
            if before.channel and before.channel.id == TRIGGER_CHANNEL_ID:
                return
            category = after.channel.category
            try:
                vc = await category.create_voice_channel(
                    name=NEW_CHANNEL_NAME, reason="Клановый канал"
                )
            except Exception as e:
                logging.error("Ошибка создания кланового канала: %s", e)
                return
            temp_channel_owners[vc.id] = member.id
            _save_owners()
            moved = False
            for m in list(after.channel.members):
                if m.bot:
                    continue
                try:
                    await m.move_to(vc, reason="Перемещение в клановый канал")
                    moved = True
                except Exception as e:
                    logging.error("Ошибка перемещения %s в клановый канал: %s", m, e)
            if not moved:
                temp_channel_owners.pop(vc.id, None)
                _save_owners()
                try:
                    await vc.delete(reason="Клановый канал: никто не перемещён")
                except Exception as e:
                    logging.error("Ошибка удаления пустого кланового канала: %s", e)
                return

        if before.channel and before.channel.id in temp_channel_owners:
            vc = before.channel
            if before.channel == after.channel:
                return
            remaining = [m for m in vc.members if not m.bot]
            if not remaining:
                await self._delete_channel(vc, reason="Клановый канал: все вышли")
            elif (
                temp_channel_owners.get(vc.id) == member.id
                and (after.channel is None or after.channel.id != vc.id)
            ):
                new_owner = remaining[0]
                temp_channel_owners[vc.id] = new_owner.id
                _save_owners()
                logging.info("Владелец канала %s теперь %s", vc.name, new_owner)

    @app_commands.command(name="temp_panel", description="Отправить панель управления клановым войсом")
    @app_commands.guilds(discord.Object(id=TEMP_GUILD_ID))
    @app_commands.guild_only()
    async def temp_panel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Только для администраторов.", ephemeral=True
            )
        embed = discord.Embed(
            title="🎛️ Управление клановым войсом",
            description=(
                "Зайдите в свой клановый канал и нажмите кнопку:\n\n"
                "🔒 **Закрыть** — закрыть/открыть канал для всех\n"
                "👢 **Выгнать** — выгнать участника из канала\n"
                "✏️ **Название** — переименовать канал\n"
                "👥 **Лимит** — ограничить число участников"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=TempChannelView())


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoice(bot))