import json
import logging
from datetime import datetime
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

import config
import database as db

GUILD_ID = 1386368131500609546

TICKET_TYPES = {
    "clan": {
        "prefix": "клан",
        "color": discord.Color.dark_red(),
        "title": "Заявка в клан",
        "button_label": "Подать заявку в клан",
        "button_style": discord.ButtonStyle.green,
        "question": (
            "**Условия вступления:**\n"
            "🔷 Возраст от 16 лет\n"
            "🔷 Адекватность\n"
            "🔷 В игре не меньше 20 часов\n"
            "🔷 Наличие микрофона\n"
            "🔷 Наличие наушников\n\n"
            "**Привет, ответь на вопросы:**\n\n"
            "**1.** Сколько тебе лет и какой опыт в Arma?\n"
            "**2.** Сколько часов в Arma?\n"
            "**3.** Есть ли у тебя микрофон?\n"
            "**4.** Во сколько и когда обычно играешь?\n"
            "**5.** Состоишь ли в других кланах?\n"
            "**6.** Готов ли выполнять требования отряда?\n"
            "**7.** Как нас нашёл или кто рекомендовал?"
        ),
    },
    "commander": {
        "prefix": "командир",
        "color": discord.Color.gold(),
        "title": "Заявка на командира группы",
        "button_label": "Подать заявку на командира группы",
        "button_style": discord.ButtonStyle.blurple,
        "question": (
            "**Привет, ответь на вопросы:**\n\n"
            "**1.** Какое звание и текущая роль?\n"
            "**2.** Есть ли опыт командования отделением в Arma?\n"
            "**3.** Как часто и где играешь?\n"
            "**4.** Готов ли вести тренировки и ивенты?\n"
            "**5.** Назови, сколько часов уже отыграл в Arma\n"
            "**6.** Почему ты хочешь стать командиром группы?\n"
            "**7.** Если есть — дай откат боя, который по твоему мнению "
            "больше всего характеризует тебя как командира группы\n"
            "**8.** Причина подачи на командира группы?"
        ),
    },
    "promotion": {
        "prefix": "повышение",
        "color": discord.Color.green(),
        "title": "Заявка на повышение",
        "button_label": "Подать заявку на повышение",
        "button_style": discord.ButtonStyle.green,
        "question": (
            "Привет, ответь на следующие вопросы:\n\n"
            "**1.** Какое звание занимаешь сейчас?\n"
            "**2.** Сколько времени состоишь в отряде?\n"
            "**3.** Насколько активно играешь в последнее время?\n"
            "**4.** Готов ли брать на себя больше ответственности?\n"
            "**5.** Скинь скриншоты или откаты, где ты или твой отряд показали "
            "себя лучшими в выполнении поставленной задачи\n"
            "**6.** Напиши, кто из отряда отличился по мнению командира отряда\n"
            "**7.** Причина для повышения?"
        ),
    },
}

ROLE_MAP = {
    "clan": config.CLAN_ROLES,
    "promotion": config.PROMOTION_ROLES,
    "commander": config.COMMANDER_ROLES,
}


def _load_tickets() -> dict:
    return db.load_tickets()


def _save_tickets(tickets: dict):
    for ticket in tickets.values():
        try:
            db.save_ticket(ticket)
        except Exception as e:
            logging.error("Ошибка сохранения тикета: %s", e)


async def _send_ticket_log(bot, title: str, description: str, color=discord.Color.blue()):
    channel = bot.get_channel(config.TICKET_LOG_CHANNEL)
    if channel is None:
        return
    embed = discord.Embed(title=title, description=description, color=color)
    try:
        await channel.send(embed=embed)
    except Exception as e:
        logging.error("Ошибка логирования тикета: %s", e)


def _is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id in config.TICKET_STAFF_ROLES for r in member.roles)


def make_create_view(ticket_type: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label=TICKET_TYPES[ticket_type]["button_label"],
            style=TICKET_TYPES[ticket_type]["button_style"],
            custom_id=f"ticket_create_{ticket_type}",
        )
    )
    return view


class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Да", style=discord.ButtonStyle.green)
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        channel = interaction.channel
        tickets = _load_tickets()
        ticket_data = tickets.get(str(channel.id))

        if ticket_data:
            ticket_data["status"] = "closed"
            ticket_data["closed_at"] = datetime.utcnow().isoformat()
            ticket_data["closed_by"] = interaction.user.id
            _save_tickets(tickets)

            creator_id = ticket_data.get("user_id")
            if creator_id:
                member = channel.guild.get_member(int(creator_id))
                if member:
                    await channel.set_permissions(member, overwrite=None)
            for role_id in config.TICKET_STAFF_ROLES:
                role = channel.guild.get_role(role_id)
                if role:
                    await channel.set_permissions(
                        role,
                        view_channel=True,
                        read_message_history=True,
                    )

        embed = discord.Embed(
            title="Заявка закрыта",
            description=f"Заявка закрыта участником {interaction.user.mention}.\n\n"
                        "Для удаления используй кнопки ниже.",
            color=discord.Color.greyple(),
        )

        await interaction.edit_original_response(embed=embed, view=TicketClosedView())

        await _send_ticket_log(
            interaction.client,
            "🔒 Заявка закрыта",
            f"**Канал:** {channel.mention}\n**Закрыл:** {interaction.user}",
            color=discord.Color.greyple(),
        )

    @discord.ui.button(label="Нет", style=discord.ButtonStyle.red)
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Закрытие отменено.", view=None)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Закрыть тикет",
        style=discord.ButtonStyle.red,
        custom_id="ticket_close",
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"DEBUG close_button fired: {interaction.user} msg={interaction.message.id if interaction.message else None}", flush=True)
        await interaction.response.send_message(
            "Ты уверен, что хочешь закрыть заявку?",
            view=TicketCloseConfirmView(),
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"DEBUG VIEW ERROR {type(error).__name__}: {error}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.followup.send("Ошибка при закрытии.", ephemeral=True)
            else:
                await interaction.response.send_message("Ошибка при закрытии.", ephemeral=True)
        except Exception:
            pass


class TicketClosedView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Удалить канал",
        style=discord.ButtonStyle.danger,
        custom_id="closed_delete",
    )
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        tickets = _load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))

        if ticket_data and interaction.user.id == ticket_data.get("user_id"):
            await interaction.followup.send("Ты не можешь удалить свой тикет.")
            return
        if not _is_staff(interaction.user):
            await interaction.followup.send("Нет прав на удаление.")
            return

        await _send_ticket_log(
            interaction.client,
            "🗑 Тикет удалён",
            f"**Канал:** {interaction.channel.name}\n**Удалил:** {interaction.user}",
            color=discord.Color.red(),
        )

        tickets.pop(str(interaction.channel.id), None)
        db.delete_ticket(interaction.channel.id)
        await interaction.channel.delete()

    @discord.ui.button(
        label="Сохранить транскрипт",
        style=discord.ButtonStyle.blurple,
        custom_id="closed_transcript",
    )
    async def save_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not _is_staff(interaction.user):
            await interaction.followup.send("Нет прав на транскрипт.")
            return

        channel = interaction.channel
        messages = [message async for message in channel.history(oldest_first=True)]

        lines = []
        for msg in messages:
            timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
            content = msg.content or ""
            if msg.embeds:
                for embed in msg.embeds:
                    if embed.description:
                        content += f" {embed.description}"
                    if embed.fields:
                        for field in embed.fields:
                            content += f"\n**{field.name}**: {field.value}"
            lines.append(f"[{timestamp}] {msg.author}: {content}")

        transcript_text = "\n".join(lines)
        file = discord.File(
            fp=BytesIO(transcript_text.encode("utf-8")),
            filename=f"transcript-{channel.name}.txt",
        )

        transcript_channel = interaction.guild.get_channel(config.TICKET_TRANSCRIPT_CHANNEL)
        if transcript_channel:
            embed = discord.Embed(
                title=f"Транскрипт: {channel.name}",
                color=discord.Color.greyple(),
                timestamp=datetime.utcnow(),
            )
            embed.set_footer(text=f"Канал: {channel.name} | Транскрипт: {interaction.user}")

            ticket_data = _load_tickets().get(str(channel.id))
            if ticket_data:
                user_id = ticket_data.get("user_id")
                embed.add_field(name="Заявитель", value=f"<@{user_id}>", inline=True)
                embed.add_field(name="Тип", value=ticket_data.get("type", "unknown"), inline=True)
                embed.add_field(name="Статус", value=ticket_data.get("status", "unknown"), inline=True)

            await transcript_channel.send(embed=embed, file=file)

        await interaction.followup.send("Транскрипт сохранён.")

    @discord.ui.button(
        label="Одобрить",
        style=discord.ButtonStyle.green,
        custom_id="closed_approve",
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not _is_staff(interaction.user):
            await interaction.followup.send("Нет прав на одобрение.")
            return

        tickets = _load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))
        if not ticket_data:
            await interaction.followup.send("Данные тикета не найдены.")
            return

        user_id = ticket_data.get("user_id")
        ticket_type = ticket_data.get("type")
        guild = interaction.guild
        member = guild.get_member(int(user_id))

        for role_id in ROLE_MAP.get(ticket_type, []):
            role = guild.get_role(role_id)
            if role and member:
                await member.add_roles(role, reason=f"Заявка одобрена: {interaction.channel.name}")

        ticket_data["status"] = "approved"
        ticket_data["approved_by"] = interaction.user.id
        ticket_data["approved_at"] = datetime.utcnow().isoformat()
        _save_tickets(tickets)

        if member:
            try:
                await member.send(
                    f"✅ Твоя заявка в **{ticket_type}** была одобрена! Поздравляем!"
                )
            except discord.Forbidden:
                pass

        embed = discord.Embed(
            title="Заявка одобрена",
            description=f"Заявка одобрена участником {interaction.user.mention}.",
            color=discord.Color.green(),
        )
        await interaction.edit_original_response(embed=embed)

        await _send_ticket_log(
            interaction.client,
            "✅ Заявка одобрена",
            f"**Канал:** {interaction.channel.mention}\n"
            f"**Заявитель:** <@{user_id}>\n**Одобрил:** {interaction.user}",
            color=discord.Color.green(),
        )

    @discord.ui.button(
        label="Отказать",
        style=discord.ButtonStyle.red,
        custom_id="closed_reject",
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not _is_staff(interaction.user):
            await interaction.followup.send("Нет прав на отказ.")
            return

        tickets = _load_tickets()
        ticket_data = tickets.get(str(interaction.channel.id))
        if not ticket_data:
            await interaction.followup.send("Данные тикета не найдены.")
            return

        user_id = ticket_data.get("user_id")
        ticket_type = ticket_data.get("type")
        guild = interaction.guild
        member = guild.get_member(int(user_id))

        ticket_data["status"] = "rejected"
        ticket_data["rejected_by"] = interaction.user.id
        ticket_data["rejected_at"] = datetime.utcnow().isoformat()
        _save_tickets(tickets)

        if member:
            try:
                await member.send(
                    f"❌ Твоя заявка в **{ticket_type}** была отклонена."
                )
            except discord.Forbidden:
                pass

        embed = discord.Embed(
            title="Заявка отклонена",
            description=f"Заявка отклонена участником {interaction.user.mention}.",
            color=discord.Color.red(),
        )
        await interaction.edit_original_response(embed=embed)

        await _send_ticket_log(
            interaction.client,
            "❌ Заявка отклонена",
            f"**Канал:** {interaction.channel.mention}\n"
            f"**Заявитель:** <@{user_id}>\n**Отклонил:** {interaction.user}",
            color=discord.Color.red(),
        )


PANEL_CONFIGS = {
    "clan": {
        "title": "ПОДАЧА ЗАЯВКИ НА ВСТУПЛЕНИЕ ЦСН-ССО «СЕНЕЖ»",
        "description": (
            "При подаче заявки важно помнить, что есть условия вступления:\n\n"
            "🔷 Возраст от 16 лет\n"
            "🔷 Адекватность\n"
            "🔷 В игре не меньше 20 часов\n"
            "🔷 Наличие микрофона\n"
            "🔷 Наличие наушников\n\n"
            "Нажми кнопку **«Подать заявку в клан»**, ответь на вопросы "
            "и персонал рассмотрит твою заявку в отдельном канале."
        ),
        "color": discord.Color.dark_red(),
    },
    "commander": {
        "title": "Подать заявку на командира группы",
        "description": (
            "Считаешь, что готов возглавить группу?\n\n"
            "Нажми кнопку **«Подать заявку на командира группы»**, "
            "и командование рассмотрит твою кандидатуру."
        ),
        "color": discord.Color.blurple(),
    },
    "promotion": {
        "title": "Подать заявку на повышение",
        "description": (
            "Готов подняться в звании?\n\n"
            "Нажми кнопку **«Подать заявку на повышение»**, "
            "и командование рассмотрит твою заявку."
        ),
        "color": discord.Color.green(),
    },
}


def make_panel_embed(ticket_type: str) -> discord.Embed:
    cfg = PANEL_CONFIGS[ticket_type]
    embed = discord.Embed(
        title=cfg["title"],
        description=cfg["description"],
        color=cfg["color"],
    )
    embed.set_footer(text="СБ-отряд «СЕНЕЖ»")
    return embed


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        data = interaction.data
        if not isinstance(data, dict):
            return
        cid = data.get("custom_id")
        if not cid or not cid.startswith("ticket_create_"):
            return
        ttype = cid[len("ticket_create_"):]
        if ttype not in TICKET_TYPES:
            return
        await interaction.response.defer(ephemeral=True)
        await self._create_ticket(interaction, ttype)

    async def _create_ticket(self, interaction: discord.Interaction, ticket_type: str):
        cfg = TICKET_TYPES[ticket_type]
        tickets = _load_tickets()

        for t in tickets.values():
            if (
                t.get("user_id") == interaction.user.id
                and t.get("status") == "open"
                and t.get("type") == ticket_type
            ):
                await interaction.followup.send(
                    "У тебя уже есть открытая заявка этого типа.", ephemeral=True
                )
                return

        user = interaction.user
        guild = interaction.guild
        category = guild.get_channel(config.TICKET_CATEGORY)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        for role_id in config.TICKET_STAFF_ROLES:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        channel_name = f"{cfg['prefix']}-{user.name}"
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Заявка от {user} ({user.id}) | тип: {ticket_type}",
        )

        embed = discord.Embed(
            title=cfg["title"],
            description=cfg["question"],
            color=cfg["color"],
            timestamp=datetime.utcnow(),
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user.id}")

        staff_mentions = " ".join(f"<@&{r}>" for r in config.TICKET_STAFF_ROLES)
        await channel.send(
            content=f"{staff_mentions} {user.mention}",
            embed=embed,
            view=TicketCloseView(),
        )

        tickets[str(channel.id)] = {
            "user_id": user.id,
            "channel_id": channel.id,
            "type": ticket_type,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
            "guild_id": guild.id,
        }
        _save_tickets(tickets)

        await _send_ticket_log(
            self.bot,
            "🎫 Тикет создан",
            f"**Канал:** {channel.mention}\n**Тип:** {ticket_type}\n**Заявитель:** {user}",
        )

        await interaction.followup.send(f"Заявка создана: {channel.mention}", ephemeral=True)

    ticket_group = app_commands.Group(
        name="tickets", description="Управление заявками", guild_ids=[GUILD_ID]
    )

    @ticket_group.command(name="clan_panel", description="Отправить панель «Заявка в клан»")
    @app_commands.describe(channel="Канал для панели")
    async def clan_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._panel(interaction, "clan", channel)

    @ticket_group.command(name="commander_panel", description="Отправить панель «Заявка на командира группы»")
    @app_commands.describe(channel="Канал для панели")
    async def commander_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._panel(interaction, "commander", channel)

    @ticket_group.command(name="promote_panel", description="Отправить панель «Заявка на повышение»")
    @app_commands.describe(channel="Канал для панели")
    async def promote_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        await self._panel(interaction, "promotion", channel)

    async def _panel(self, interaction: discord.Interaction, ticket_type: str, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "У тебя нет прав на отправку панели.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel
        await target.send(embed=make_panel_embed(ticket_type), view=make_create_view(ticket_type))
        mention = f" в {channel.mention}" if channel else ""
        await interaction.followup.send(f"Панель отправлена{mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))