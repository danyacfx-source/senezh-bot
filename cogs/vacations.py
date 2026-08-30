import json
import os
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

VACATION_RETURN_NOTIFIED = set()


def _data_path():
    return os.path.join(os.getcwd(), config.VACATION_FILE)


def load_vacations():
    path = _data_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop("__panel__", None)
    return data


def save_vacations(data):
    path = _data_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = {}
    panel_info = raw.get("__panel__")
    out = dict(data)
    if panel_info:
        out["__panel__"] = panel_info
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)


async def send_vacation_log(bot, title, description, color=discord.Color.orange()):
    channel = bot.get_channel(config.VACATION_LOG_CHANNEL)
    if channel:
        embed = discord.Embed(title=title, description=description, color=color)
        try:
            await channel.send(embed=embed)
        except Exception:
            pass


def build_info_panel_embed(data):
    embed = discord.Embed(
        title="Система отпусков | Информация",
        color=discord.Color.orange(),
    )

    entries = []
    for uid, v in data.items():
        if uid == "__panel__" or not isinstance(v, dict):
            continue
        periods = v.get("periods", [])
        if not periods:
            continue

        user_name = v.get("user_name", f"<@{uid}>")
        lines = [f"<@{uid}>"]

        for p in periods:
            start_d = p.get("start_date", "")
            end_d = p.get("end_date", "")
            reason = p.get("reason", "")

            if start_d:
                lines.append(f"от {start_d} до {end_d}")
            else:
                lines.append(f"до {end_d}")
            if reason:
                lines.append(reason)

        entries.append("\n".join(lines))

    if entries:
        embed.description = "\n\n".join(entries)
    else:
        embed.description = "Нет активных отпусков"

    embed.set_footer(text="Сделано с ❤️ от Денди")
    return embed


def build_request_panel_embed():
    embed = discord.Embed(
        title="Система отпусков | Панель",
        description=(
            "Нажмите кнопку ниже, чтобы подать заявку на отпуск.\n\n"
            "🔹 **Взять отпуск** — подать заявку\n"
            "🔹 **Статус** — посмотреть свои отпуска\n"
            "🔹 **Продлить отпуск** — продлить текущий отпуск\n"
            "🔹 **Снять отпуск** — отменить текущий отпуск"
        ),
        color=discord.Color.blurple(),
    )
    return embed


async def update_vacation_panel(bot):
    path = _data_path()
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    panel_data = raw.get("__panel__")
    if not panel_data:
        return
    channel = bot.get_channel(panel_data.get("channel_id"))
    if not channel:
        return
    try:
        info_msg = await channel.fetch_message(panel_data.get("info_message_id"))
        embed_data = {k: v for k, v in raw.items() if k != "__panel__"}
        embed = build_info_panel_embed(embed_data)
        await info_msg.edit(embed=embed)
    except Exception:
        pass
    try:
        request_msg = await channel.fetch_message(panel_data.get("request_message_id"))
        embed = build_request_panel_embed()
        await request_msg.edit(embed=embed)
    except Exception:
        pass


class VacationModal(discord.ui.Modal, title="Заявка на отпуск"):
    start_date = discord.ui.TextInput(
        label="Дата начала (ДД.ММ.ГГГГ)",
        placeholder="25.07.2026",
        required=True,
        max_length=10,
    )
    end_date = discord.ui.TextInput(
        label="Дата окончания (ДД.ММ.ГГГГ)",
        placeholder="10.08.2026",
        required=True,
        max_length=10,
    )
    reason = discord.ui.TextInput(
        label="Причина",
        placeholder="Укажите причину отпуска",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start = datetime.strptime(self.start_date.value.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message(
                "❌ Неверный формат даты начала. Используйте ДД.ММ.ГГГГ.", ephemeral=True
            )
            return

        try:
            end = datetime.strptime(self.end_date.value.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message(
                "❌ Неверный формат даты окончания. Используйте ДД.ММ.ГГГГ.", ephemeral=True
            )
            return

        if end < start:
            await interaction.response.send_message(
                "❌ Дата окончания не может быть раньше даты начала.", ephemeral=True
            )
            return

        reason = self.reason.value.strip()

        vacations = load_vacations()
        user_id_str = str(interaction.user.id)

        if user_id_str not in vacations:
            vacations[user_id_str] = {
                "user_name": str(interaction.user),
                "periods": [],
            }

        vacation = vacations[user_id_str]
        vacation["user_name"] = str(interaction.user)
        vacation["periods"].append({
            "start_date": start.strftime("%d.%m.%Y"),
            "end_date": end.strftime("%d.%m.%Y"),
            "reason": reason,
        })

        save_vacations(vacations)

        role = interaction.guild.get_role(config.VACATION_ROLE_ID)
        if role:
            await interaction.user.add_roles(role, reason="Одобрена заявка на отпуск")

        days = (end - start).days + 1
        await interaction.response.send_message(
            f"✅ Ваш отпуск одобрен!\n"
            f"📅 С **{start.strftime('%d.%m.%Y')}** по **{end.strftime('%d.%m.%Y')}** ({days} дн.)",
            ephemeral=True,
        )

        await send_vacation_log(
            interaction.client,
            "🏖️ Отпуск одобрен",
            f"**Пользователь:** {interaction.user.mention}\n"
            f"**Период:** {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')} ({days} дн.)\n"
            f"**Причина:** {reason}",
        )

        await update_vacation_panel(interaction.client)


class VacationExtendModal(discord.ui.Modal, title="Продление отпуска"):
    extra_days = discord.ui.TextInput(
        label="Дополнительные дни",
        placeholder="3",
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            extra = int(self.extra_days.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Количество дней должно быть числом.", ephemeral=True
            )
            return
        if extra <= 0:
            await interaction.response.send_message(
                "❌ Количество дней должно быть больше нуля.", ephemeral=True
            )
            return

        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message(
                "❌ У вас нет активного отпуска.", ephemeral=True
            )
            return

        v = vacations[user_id_str]
        periods = v.get("periods", [])
        now = datetime.now()

        target = None
        for p in periods:
            try:
                end = datetime.strptime(p["end_date"], "%d.%m.%Y")
                if end >= now:
                    target = p
                    break
            except (KeyError, ValueError):
                continue

        if not target:
            await interaction.response.send_message(
                "❌ У вас нет текущего отпуска для продления.", ephemeral=True
            )
            return

        old_end = datetime.strptime(target["end_date"], "%d.%m.%Y")
        new_end = old_end + timedelta(days=extra)
        target["end_date"] = new_end.strftime("%d.%m.%Y")
        save_vacations(vacations)

        await interaction.response.send_message(
            f"✅ Отпуск продлён на **{extra}** дн.\n"
            f"📅 Новая дата окончания: **{new_end.strftime('%d.%m.%Y')}**",
            ephemeral=True,
        )

        await send_vacation_log(
            interaction.client,
            "🔄 Отпуск продлён",
            f"**Пользователь:** {interaction.user.mention}\n"
            f"**Продление:** {extra} дн.\n"
            f"**Новая дата окончания:** {new_end.strftime('%d.%m.%Y')}",
        )

        await update_vacation_panel(interaction.client)


class RequestVacationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 Взять отпуск",
        style=discord.ButtonStyle.green,
        custom_id="senezh_vacation_request",
    )
    async def request_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VacationModal())

    @discord.ui.button(
        label="📋 Статус",
        style=discord.ButtonStyle.blurple,
        custom_id="senezh_vacation_status",
    )
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message("❌ У вас нет отпусков.", ephemeral=True)
            return
        v = vacations[user_id_str]
        embed = discord.Embed(title="🏖️ Ваши отпуска", color=discord.Color.blue())
        for i, p in enumerate(v.get("periods", []), 1):
            embed.add_field(
                name=f"Период {i}",
                value=f"📅 {p['start_date']} — {p['end_date']}\n📝 {p['reason']}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="🔄 Продлить отпуск",
        style=discord.ButtonStyle.success,
        custom_id="senezh_vacation_extend",
    )
    async def extend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VacationExtendModal())

    @discord.ui.button(
        label="❌ Снять отпуск",
        style=discord.ButtonStyle.red,
        custom_id="senezh_vacation_cancel",
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vacations = load_vacations()
        user_id_str = str(interaction.user.id)
        if user_id_str not in vacations:
            await interaction.response.send_message("❌ У вас нет отпусков.", ephemeral=True)
            return

        count = len(vacations[user_id_str].get("periods", []))
        del vacations[user_id_str]
        save_vacations(vacations)

        role = interaction.guild.get_role(config.VACATION_ROLE_ID)
        if role:
            await interaction.user.remove_roles(role, reason="Отпуск снят")

        await interaction.response.send_message(
            f"✅ Снято {count} период(ов) отпуска.", ephemeral=True
        )

        await send_vacation_log(
            interaction.client,
            "❌ Отпуск снят",
            f"**Пользователь:** {interaction.user.mention} снял {count} период(ов) отпуска.",
        )

        await update_vacation_panel(interaction.client)


class VacationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.vacation_return_check.start()

    @app_commands.command(
        name="vacation_panel",
        description="Отправить панель отпусков",
    )
    @app_commands.default_permissions(administrator=True)
    async def vacation_panel(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(config.VACATION_PANEL_CHANNEL)
        if channel is None:
            await interaction.response.send_message(
                "❌ Канал панели отпусков не найден. Проверь config.VACATION_PANEL_CHANNEL.",
                ephemeral=True,
            )
            return

        info_embed = build_info_panel_embed(load_vacations())
        info_msg = await channel.send(embed=info_embed)

        request_embed = build_request_panel_embed()
        request_view = RequestVacationView()
        request_msg = await channel.send(embed=request_embed, view=request_view)

        path = _data_path()
        raw = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        raw["__panel__"] = {
            "channel_id": channel.id,
            "info_message_id": info_msg.id,
            "request_message_id": request_msg.id,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=4)

        await interaction.response.send_message(
            f"✅ Панель отпусков отправлена в {channel.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="vacation_list",
        description="Показать все отпуска",
    )
    @app_commands.default_permissions(administrator=True)
    async def vacation_list(self, interaction: discord.Interaction):
        vacations = load_vacations()
        real_vacations = {
            k: v for k, v in vacations.items() if k != "__panel__" and isinstance(v, dict)
        }

        if not real_vacations:
            await interaction.response.send_message("📋 Отпусков нет.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Все отпуска",
            color=discord.Color.blue(),
        )

        for user_id_str, v in real_vacations.items():
            name = v.get("user_name", f"ID: {user_id_str}")
            periods = v.get("periods", [])
            lines = []
            for p in periods:
                lines.append(f"📅 {p.get('start_date', '—')} — {p.get('end_date', '—')}\n📝 {p.get('reason', '—')}")
            embed.add_field(
                name=name,
                value="\n\n".join(lines) if lines else "Нет периодов",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="vacation_remove",
        description="Снять отпуск у участника",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="Участник, у которого снять отпуск")
    async def vacation_remove(self, interaction: discord.Interaction, user: discord.Member):
        vacations = load_vacations()
        user_id_str = str(user.id)

        if user_id_str not in vacations:
            await interaction.response.send_message(
                f"❌ У {user.mention} нет отпусков.", ephemeral=True
            )
            return

        v = vacations[user_id_str]
        periods = v.get("periods", [])
        count = len(periods)
        del vacations[user_id_str]
        save_vacations(vacations)

        role = interaction.guild.get_role(config.VACATION_ROLE_ID)
        if role and role in user.roles:
            await user.remove_roles(role, reason="Отпуск снят администратором")

        await interaction.response.send_message(
            f"✅ Все отпуски ({count} период(ов)) у {user.mention} сняты.",
            ephemeral=True,
        )

        await send_vacation_log(
            interaction.client,
            "🗑️ Отпуск снят (вручную)",
            f"**Пользователь:** {user.mention}\n"
            f"**Снял:** {interaction.user.mention}\n"
            f"**Количество периодов:** {count}",
            color=discord.Color.red(),
        )

        await update_vacation_panel(self.bot)

    @tasks.loop(minutes=1)
    async def vacation_return_check(self):
        now = datetime.now()

        if now.hour != 10 or now.minute > 2:
            return

        global VACATION_RETURN_NOTIFIED
        vacations = load_vacations()

        for user_id_str, v in vacations.items():
            if user_id_str == "__panel__":
                continue
            if not isinstance(v, dict):
                continue

            user_name = v.get("user_name", f"<@{user_id_str}>")
            for p in v.get("periods", []):
                try:
                    end_date = datetime.strptime(p["end_date"], "%d.%m.%Y")
                except (KeyError, ValueError):
                    continue

                days_overdue = (now.date() - end_date.date()).days
                key = f"{user_id_str}_{p['end_date']}"

                if days_overdue >= 5 and key not in VACATION_RETURN_NOTIFIED:
                    channel = self.bot.get_channel(config.VACATION_RETURN_CHANNEL)
                    if channel:
                        try:
                            ping = " ".join(f"<@&{r}>" for r in config.VACATION_PING_ROLES)
                            await channel.send(
                                f"{ping}\n"
                                f"⚠️ **{user_name}** — "
                                f"отпуск истёк **{days_overdue}** дн. назад "
                                f"(дата окончания: {p['end_date']})."
                            )
                            VACATION_RETURN_NOTIFIED.add(key)
                        except Exception:
                            pass

    @vacation_return_check.before_loop
    async def before_vacation_return_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(VacationCog(bot))