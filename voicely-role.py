from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "voicely-role.db"
DEFAULT_MESSAGE = "🔊 {role} There are now **{count} people** in {channel}!"
DEFAULT_ENDED_MESSAGE = "🔇 Everyone has left {channel}."
MAX_CUSTOM_MESSAGE_LENGTH = 1500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voicely-role")


@dataclass(slots=True)
class Notification:
    id: int
    guild_id: int
    name: str
    threshold: int
    role_id: int
    destination_channel_id: int
    message_template: str
    ended_message_template: str


class Database:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self.lock:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    threshold INTEGER NOT NULL CHECK (threshold >= 1),
                    role_id INTEGER NOT NULL,
                    destination_channel_id INTEGER NOT NULL,
                    message_template TEXT NOT NULL,
                    ended_message_template TEXT NOT NULL DEFAULT '🔇 Everyone has left {channel}.'
                );

                CREATE TABLE IF NOT EXISTS notification_voice_channels (
                    notification_id INTEGER NOT NULL,
                    voice_channel_id INTEGER NOT NULL,
                    PRIMARY KEY (notification_id, voice_channel_id),
                    FOREIGN KEY (notification_id)
                        REFERENCES notifications(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS trigger_states (
                    notification_id INTEGER NOT NULL,
                    voice_channel_id INTEGER NOT NULL,
                    triggered INTEGER NOT NULL DEFAULT 0,
                    message_id INTEGER,
                    PRIMARY KEY (notification_id, voice_channel_id),
                    FOREIGN KEY (notification_id, voice_channel_id)
                        REFERENCES notification_voice_channels(
                            notification_id,
                            voice_channel_id
                        )
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS admin_roles (
                    guild_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, role_id)
                );

                CREATE TABLE IF NOT EXISTS excluded_users (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_notifications_guild
                    ON notifications(guild_id);

                CREATE INDEX IF NOT EXISTS idx_watched_voice_channel
                    ON notification_voice_channels(voice_channel_id);
                """
            )

            notification_columns = {
                str(row["name"])
                for row in self.connection.execute(
                    "PRAGMA table_info(notifications)"
                ).fetchall()
            }
            if "ended_message_template" not in notification_columns:
                self.connection.execute(
                    """
                    ALTER TABLE notifications
                    ADD COLUMN ended_message_template TEXT NOT NULL
                    DEFAULT '🔇 Everyone has left {channel}.'
                    """
                )

            trigger_state_columns = {
                str(row["name"])
                for row in self.connection.execute(
                    "PRAGMA table_info(trigger_states)"
                ).fetchall()
            }
            if "message_id" not in trigger_state_columns:
                self.connection.execute(
                    "ALTER TABLE trigger_states ADD COLUMN message_id INTEGER"
                )

            self.connection.commit()

    async def create_notification(
        self,
        guild_id: int,
        name: str,
        threshold: int,
        role_id: int,
        destination_channel_id: int,
        message_template: str,
        ended_message_template: str,
        voice_channel_ids: Iterable[int],
    ) -> int:
        channel_ids = list(dict.fromkeys(voice_channel_ids))
        async with self.lock:
            cursor = self.connection.execute(
                """
                INSERT INTO notifications (
                    guild_id,
                    name,
                    threshold,
                    role_id,
                    destination_channel_id,
                    message_template,
                    ended_message_template
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    name,
                    threshold,
                    role_id,
                    destination_channel_id,
                    message_template,
                    ended_message_template,
                ),
            )
            notification_id = int(cursor.lastrowid)

            self.connection.executemany(
                """
                INSERT INTO notification_voice_channels (
                    notification_id,
                    voice_channel_id
                ) VALUES (?, ?)
                """,
                [(notification_id, channel_id) for channel_id in channel_ids],
            )
            self.connection.executemany(
                """
                INSERT INTO trigger_states (
                    notification_id,
                    voice_channel_id,
                    triggered
                ) VALUES (?, ?, 0)
                """,
                [(notification_id, channel_id) for channel_id in channel_ids],
            )
            self.connection.commit()
            return notification_id

    async def get_notifications(self, guild_id: int) -> list[Notification]:
        async with self.lock:
            rows = self.connection.execute(
                """
                SELECT *
                FROM notifications
                WHERE guild_id = ?
                ORDER BY id
                """,
                (guild_id,),
            ).fetchall()
        return [self._notification_from_row(row) for row in rows]

    async def get_notification(
        self,
        guild_id: int,
        notification_id: int,
    ) -> Notification | None:
        async with self.lock:
            row = self.connection.execute(
                """
                SELECT *
                FROM notifications
                WHERE guild_id = ? AND id = ?
                """,
                (guild_id, notification_id),
            ).fetchone()
        return self._notification_from_row(row) if row else None

    async def get_voice_channel_ids(self, notification_id: int) -> list[int]:
        async with self.lock:
            rows = self.connection.execute(
                """
                SELECT voice_channel_id
                FROM notification_voice_channels
                WHERE notification_id = ?
                ORDER BY voice_channel_id
                """,
                (notification_id,),
            ).fetchall()
        return [int(row["voice_channel_id"]) for row in rows]

    async def get_notifications_for_voice_channel(
        self,
        guild_id: int,
        voice_channel_id: int,
    ) -> list[tuple[Notification, bool, int | None]]:
        async with self.lock:
            rows = self.connection.execute(
                """
                SELECT n.*, s.triggered, s.message_id
                FROM notifications AS n
                JOIN notification_voice_channels AS c
                    ON c.notification_id = n.id
                JOIN trigger_states AS s
                    ON s.notification_id = n.id
                    AND s.voice_channel_id = c.voice_channel_id
                WHERE n.guild_id = ?
                    AND c.voice_channel_id = ?
                ORDER BY n.id
                """,
                (guild_id, voice_channel_id),
            ).fetchall()

        return [
            (
                self._notification_from_row(row),
                bool(row["triggered"]),
                int(row["message_id"]) if row["message_id"] is not None else None,
            )
            for row in rows
        ]

    async def set_triggered(
        self,
        notification_id: int,
        voice_channel_id: int,
        triggered: bool,
    ) -> None:
        async with self.lock:
            self.connection.execute(
                """
                UPDATE trigger_states
                SET triggered = ?
                WHERE notification_id = ? AND voice_channel_id = ?
                """,
                (int(triggered), notification_id, voice_channel_id),
            )
            self.connection.commit()

    async def set_message_id(
        self,
        notification_id: int,
        voice_channel_id: int,
        message_id: int | None,
    ) -> None:
        async with self.lock:
            self.connection.execute(
                """
                UPDATE trigger_states
                SET message_id = ?
                WHERE notification_id = ? AND voice_channel_id = ?
                """,
                (message_id, notification_id, voice_channel_id),
            )
            self.connection.commit()

    async def clear_trigger_state(
        self,
        notification_id: int,
        voice_channel_id: int,
    ) -> None:
        async with self.lock:
            self.connection.execute(
                """
                UPDATE trigger_states
                SET triggered = 0, message_id = NULL
                WHERE notification_id = ? AND voice_channel_id = ?
                """,
                (notification_id, voice_channel_id),
            )
            self.connection.commit()

    async def delete_notification(self, guild_id: int, notification_id: int) -> bool:
        async with self.lock:
            cursor = self.connection.execute(
                """
                DELETE FROM notifications
                WHERE guild_id = ? AND id = ?
                """,
                (guild_id, notification_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def update_messages(
        self,
        guild_id: int,
        notification_id: int,
        message_template: str,
        ended_message_template: str,
    ) -> bool:
        async with self.lock:
            cursor = self.connection.execute(
                """
                UPDATE notifications
                SET message_template = ?, ended_message_template = ?
                WHERE guild_id = ? AND id = ?
                """,
                (
                    message_template,
                    ended_message_template,
                    guild_id,
                    notification_id,
                ),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def get_excluded_user_ids(self, guild_id: int) -> set[int]:
        async with self.lock:
            rows = self.connection.execute(
                """
                SELECT user_id
                FROM excluded_users
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchall()
        return {int(row["user_id"]) for row in rows}

    async def exclude_user(self, guild_id: int, user_id: int) -> bool:
        async with self.lock:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO excluded_users (guild_id, user_id)
                VALUES (?, ?)
                """,
                (guild_id, user_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def include_user(self, guild_id: int, user_id: int) -> bool:
        async with self.lock:
            cursor = self.connection.execute(
                """
                DELETE FROM excluded_users
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    async def get_admin_role_ids(self, guild_id: int) -> set[int]:
        async with self.lock:
            rows = self.connection.execute(
                """
                SELECT role_id
                FROM admin_roles
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchall()
        return {int(row["role_id"]) for row in rows}

    async def set_admin_roles(self, guild_id: int, role_ids: Iterable[int]) -> None:
        unique_role_ids = list(dict.fromkeys(role_ids))
        async with self.lock:
            self.connection.execute(
                "DELETE FROM admin_roles WHERE guild_id = ?",
                (guild_id,),
            )
            self.connection.executemany(
                """
                INSERT INTO admin_roles (guild_id, role_id)
                VALUES (?, ?)
                """,
                [(guild_id, role_id) for role_id in unique_role_ids],
            )
            self.connection.commit()

    async def remove_guild(self, guild_id: int) -> None:
        async with self.lock:
            self.connection.execute(
                "DELETE FROM notifications WHERE guild_id = ?",
                (guild_id,),
            )
            self.connection.execute(
                "DELETE FROM admin_roles WHERE guild_id = ?",
                (guild_id,),
            )
            self.connection.execute(
                "DELETE FROM excluded_users WHERE guild_id = ?",
                (guild_id,),
            )
            self.connection.commit()

    @staticmethod
    def _notification_from_row(row: sqlite3.Row) -> Notification:
        return Notification(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            name=str(row["name"]),
            threshold=int(row["threshold"]),
            role_id=int(row["role_id"]),
            destination_channel_id=int(row["destination_channel_id"]),
            message_template=str(row["message_template"]),
            ended_message_template=str(row["ended_message_template"]),
        )


class RestrictedView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 900) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who opened this menu can use it.",
                ephemeral=True,
            )
            return False
        return True


class NotificationDetailsModal(discord.ui.Modal, title="Notification details"):
    name = discord.ui.TextInput(
        label="Notification name",
        placeholder="For example: General gaming ping",
        max_length=80,
    )
    threshold = discord.ui.TextInput(
        label="People required",
        placeholder="2",
        max_length=3,
    )
    message = discord.ui.TextInput(
        label="Active message (optional)",
        placeholder=DEFAULT_MESSAGE,
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_CUSTOM_MESSAGE_LENGTH,
    )
    ended_message = discord.ui.TextInput(
        label="Message when everyone leaves (optional)",
        placeholder=DEFAULT_ENDED_MESSAGE,
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=MAX_CUSTOM_MESSAGE_LENGTH,
    )

    def __init__(self, setup_view: AddNotificationView) -> None:
        super().__init__()
        self.setup_view = setup_view
        if setup_view.name_value:
            self.name.default = setup_view.name_value
        if setup_view.threshold_value is not None:
            self.threshold.default = str(setup_view.threshold_value)
        if setup_view.message_value != DEFAULT_MESSAGE:
            self.message.default = setup_view.message_value
        if setup_view.ended_message_value != DEFAULT_ENDED_MESSAGE:
            self.ended_message.default = setup_view.ended_message_value

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            threshold = int(str(self.threshold.value).strip())
        except ValueError:
            await interaction.response.send_message(
                "The number of people must be a whole number.",
                ephemeral=True,
            )
            return

        if threshold < 1 or threshold > 999:
            await interaction.response.send_message(
                "The number of people must be between 1 and 999.",
                ephemeral=True,
            )
            return

        message = str(self.message.value).strip() or DEFAULT_MESSAGE
        ended_message = (
            str(self.ended_message.value).strip() or DEFAULT_ENDED_MESSAGE
        )
        unknown_placeholders = (
            find_unknown_placeholders(message)
            | find_unknown_placeholders(ended_message)
        )
        if unknown_placeholders:
            formatted = ", ".join(f"`{{{item}}}`" for item in unknown_placeholders)
            await interaction.response.send_message(
                f"Unknown message placeholder(s): {formatted}",
                ephemeral=True,
            )
            return

        self.setup_view.name_value = str(self.name.value).strip()
        self.setup_view.threshold_value = threshold
        self.setup_view.message_value = message
        self.setup_view.ended_message_value = ended_message
        await interaction.response.edit_message(
            content=self.setup_view.summary(),
            view=self.setup_view,
        )


class VoiceChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, setup_view: AddNotificationView) -> None:
        super().__init__(
            placeholder="Select voice channels",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=25,
            row=0,
        )
        self.setup_view = setup_view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.setup_view.voice_channel_ids = [channel.id for channel in self.values]
        await interaction.response.edit_message(
            content=self.setup_view.summary(),
            view=self.setup_view,
        )


class RolePicker(discord.ui.RoleSelect):
    def __init__(self, setup_view: AddNotificationView) -> None:
        super().__init__(
            placeholder="Select the role to ping",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.setup_view = setup_view

    async def callback(self, interaction: discord.Interaction) -> None:
        role = self.values[0]
        if role.is_default():
            await interaction.response.send_message(
                "The @everyone role cannot be selected.",
                ephemeral=True,
            )
            return
        self.setup_view.role_id = role.id
        await interaction.response.edit_message(
            content=self.setup_view.summary(),
            view=self.setup_view,
        )


class DestinationChannelPicker(discord.ui.Select):
    def __init__(self, setup_view: AddNotificationView) -> None:
        self.setup_view = setup_view
        channels = setup_view.destination_page_channels()
        options = [
            discord.SelectOption(
                label=channel.name[:100],
                value=str(channel.id),
                description=(
                    f"Category: {channel.category.name}"
                    if channel.category
                    else "No category"
                )[:100],
                default=channel.id == setup_view.destination_channel_id,
            )
            for channel in channels
        ]
        super().__init__(
            placeholder="Select the text channel for the ping",
            options=options,
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.setup_view.destination_channel_id = int(self.values[0])
        self.setup_view.rebuild_items()
        await interaction.response.edit_message(
            content=self.setup_view.summary(),
            view=self.setup_view,
        )


class AddNotificationView(RestrictedView):
    def __init__(
        self,
        owner_id: int,
        guild: discord.Guild,
        database: Database,
    ) -> None:
        super().__init__(owner_id)
        self.guild = guild
        self.database = database
        self.voice_channel_ids: list[int] = []
        self.role_id: int | None = None
        self.destination_channel_id: int | None = None
        self.name_value = ""
        self.threshold_value: int | None = None
        self.message_value = DEFAULT_MESSAGE
        self.ended_message_value = DEFAULT_ENDED_MESSAGE
        self.destination_page = 0
        self.accessible_text_channels = [
            channel
            for channel in guild.text_channels
            if guild.me is not None
            and channel.permissions_for(guild.me).view_channel
            and channel.permissions_for(guild.me).send_messages
        ]
        self.rebuild_items()

    @property
    def destination_page_count(self) -> int:
        return max(1, (len(self.accessible_text_channels) + 24) // 25)

    def destination_page_channels(self) -> list[discord.TextChannel]:
        start = self.destination_page * 25
        return self.accessible_text_channels[start : start + 25]

    def rebuild_items(self) -> None:
        self.clear_items()
        self.add_item(VoiceChannelPicker(self))
        self.add_item(RolePicker(self))
        if self.accessible_text_channels:
            self.add_item(DestinationChannelPicker(self))

        if self.destination_page_count > 1:
            previous = discord.ui.Button(
                label="Previous text channels",
                style=discord.ButtonStyle.secondary,
                disabled=self.destination_page == 0,
                row=3,
            )
            previous.callback = self.previous_destination_page
            self.add_item(previous)

            next_button = discord.ui.Button(
                label="Next text channels",
                style=discord.ButtonStyle.secondary,
                disabled=self.destination_page >= self.destination_page_count - 1,
                row=3,
            )
            next_button.callback = self.next_destination_page
            self.add_item(next_button)

        details = discord.ui.Button(
            label="Enter details",
            style=discord.ButtonStyle.secondary,
            row=4,
        )
        details.callback = self.open_details
        self.add_item(details)

        save = discord.ui.Button(
            label="Save notification",
            style=discord.ButtonStyle.success,
            row=4,
        )
        save.callback = self.save_notification
        self.add_item(save)

        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            row=4,
        )
        cancel.callback = self.cancel_setup
        self.add_item(cancel)

    async def previous_destination_page(self, interaction: discord.Interaction) -> None:
        self.destination_page -= 1
        self.rebuild_items()
        await interaction.response.edit_message(content=self.summary(), view=self)

    async def next_destination_page(self, interaction: discord.Interaction) -> None:
        self.destination_page += 1
        self.rebuild_items()
        await interaction.response.edit_message(content=self.summary(), view=self)

    def summary(self) -> str:
        channels = (
            ", ".join(f"<#{channel_id}>" for channel_id in self.voice_channel_ids)
            if self.voice_channel_ids
            else "*Not selected*"
        )
        role = f"<@&{self.role_id}>" if self.role_id else "*Not selected*"
        destination = (
            f"<#{self.destination_channel_id}>"
            if self.destination_channel_id
            else "*Not selected*"
        )
        details = (
            f"**{discord.utils.escape_markdown(self.name_value)}** — "
            f"{self.threshold_value} people"
            if self.name_value and self.threshold_value is not None
            else "*Not entered*"
        )
        return (
            "## Add a Voicely Role notification\n"
            f"**Voice channels:** {channels}\n"
            f"**Role:** {role}\n"
            f"**Ping channel:** {destination}\n"
            f"**Details:** {details}\n\n"
            "Use the dropdowns, enter the details, and then save."
            + (
                "\n\n⚠️ I cannot currently send messages in any server text channel."
                if not self.accessible_text_channels
                else ""
            )
        )

    async def open_details(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(NotificationDetailsModal(self))

    async def save_notification(self, interaction: discord.Interaction) -> None:
        if not self.voice_channel_ids:
            await interaction.response.send_message(
                "Select at least one voice channel.",
                ephemeral=True,
            )
            return
        if self.role_id is None:
            await interaction.response.send_message(
                "Select a role to ping.",
                ephemeral=True,
            )
            return
        if self.destination_channel_id is None:
            await interaction.response.send_message(
                "Select the text channel where the ping should be sent.",
                ephemeral=True,
            )
            return
        if not self.name_value or self.threshold_value is None:
            await interaction.response.send_message(
                "Select **Enter details** and provide a name and threshold.",
                ephemeral=True,
            )
            return

        destination = self.guild.get_channel(self.destination_channel_id)
        if not isinstance(destination, discord.TextChannel):
            await interaction.response.send_message(
                "The selected destination channel no longer exists.",
                ephemeral=True,
            )
            return

        bot_member = self.guild.me
        if bot_member is None:
            await interaction.response.send_message(
                "I could not verify my server permissions.",
                ephemeral=True,
            )
            return

        permissions = destination.permissions_for(bot_member)
        if not permissions.view_channel or not permissions.send_messages:
            await interaction.response.send_message(
                "I no longer have permission to send messages in the selected channel.",
                ephemeral=True,
            )
            return

        notification_id = await self.database.create_notification(
            guild_id=self.guild.id,
            name=self.name_value,
            threshold=self.threshold_value,
            role_id=self.role_id,
            destination_channel_id=self.destination_channel_id,
            message_template=self.message_value,
            ended_message_template=self.ended_message_value,
            voice_channel_ids=self.voice_channel_ids,
        )

        for voice_channel_id in self.voice_channel_ids:
            voice_channel = self.guild.get_channel(voice_channel_id)
            if not isinstance(voice_channel, discord.VoiceChannel):
                continue
            count = await counted_human_count(voice_channel, self.database)
            if count >= self.threshold_value:
                await self.database.set_triggered(
                    notification_id,
                    voice_channel_id,
                    True,
                )

        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=(
                f"✅ Created **{discord.utils.escape_markdown(self.name_value)}** "
                f"with ID `{notification_id}`."
            ),
            view=self,
        )

    async def cancel_setup(self, interaction: discord.Interaction) -> None:
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Setup cancelled.", view=self)


class AdminRolePicker(discord.ui.RoleSelect):
    def __init__(self, view: AdminRolesView) -> None:
        super().__init__(
            placeholder="Select all Voicely Role admin roles",
            min_values=0,
            max_values=25,
            row=0,
        )
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        role_ids = [role.id for role in self.values if not role.is_default()]
        await self.parent_view.database.set_admin_roles(
            self.parent_view.guild_id,
            role_ids,
        )
        mentions = ", ".join(f"<@&{role_id}>" for role_id in role_ids)
        message = (
            f"✅ Voicely Role admin roles are now: {mentions}"
            if mentions
            else "✅ All Voicely Role admin roles were removed. Discord Administrators still have access."
        )
        await interaction.response.edit_message(content=message, view=None)
        self.parent_view.stop()


class AdminRolesView(RestrictedView):
    def __init__(self, owner_id: int, guild_id: int, database: Database) -> None:
        super().__init__(owner_id)
        self.guild_id = guild_id
        self.database = database
        self.add_item(AdminRolePicker(self))

    @discord.ui.button(
        label="Clear admin roles",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def clear_admin_roles(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.database.set_admin_roles(self.guild_id, [])
        self.stop()
        await interaction.response.edit_message(
            content=(
                "✅ All Voicely Role admin roles were removed. "
                "Discord Administrators still have access."
            ),
            view=None,
        )


class NotificationSelect(discord.ui.Select):
    def __init__(
        self,
        parent_view: NotificationPagedView,
        notifications: list[Notification],
    ) -> None:
        self.parent_view = parent_view
        options = [
            discord.SelectOption(
                label=notification.name[:100],
                value=str(notification.id),
                description=(
                    f"Threshold {notification.threshold} • ID {notification.id}"
                )[:100],
            )
            for notification in notifications
        ]
        super().__init__(
            placeholder=parent_view.placeholder,
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.parent_view.notification_selected(
            interaction,
            int(self.values[0]),
        )


class NotificationPagedView(RestrictedView):
    PAGE_SIZE = 25

    def __init__(
        self,
        owner_id: int,
        notifications: list[Notification],
        placeholder: str,
    ) -> None:
        super().__init__(owner_id)
        self.notifications = notifications
        self.placeholder = placeholder
        self.page = 0
        self._rebuild()

    @property
    def page_count(self) -> int:
        return max(1, (len(self.notifications) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    def _rebuild(self) -> None:
        self.clear_items()
        start = self.page * self.PAGE_SIZE
        page_items = self.notifications[start : start + self.PAGE_SIZE]
        self.add_item(NotificationSelect(self, page_items))

        if self.page_count > 1:
            previous = discord.ui.Button(
                label="Previous",
                style=discord.ButtonStyle.secondary,
                disabled=self.page == 0,
                row=1,
            )
            previous.callback = self.previous_page
            self.add_item(previous)

            next_button = discord.ui.Button(
                label="Next",
                style=discord.ButtonStyle.secondary,
                disabled=self.page >= self.page_count - 1,
                row=1,
            )
            next_button.callback = self.next_page
            self.add_item(next_button)

    async def previous_page(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(
            content=self.page_heading(),
            view=self,
        )

    async def next_page(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(
            content=self.page_heading(),
            view=self,
        )

    def page_heading(self) -> str:
        return f"Page {self.page + 1} of {self.page_count}"

    async def notification_selected(
        self,
        interaction: discord.Interaction,
        notification_id: int,
    ) -> None:
        raise NotImplementedError


class RemoveNotificationView(NotificationPagedView):
    def __init__(
        self,
        owner_id: int,
        guild_id: int,
        database: Database,
        notifications: list[Notification],
    ) -> None:
        self.guild_id = guild_id
        self.database = database
        super().__init__(owner_id, notifications, "Select a notification to remove")

    async def notification_selected(
        self,
        interaction: discord.Interaction,
        notification_id: int,
    ) -> None:
        notification = next(
            (item for item in self.notifications if item.id == notification_id),
            None,
        )
        if notification is None:
            await interaction.response.send_message(
                "That notification no longer exists.",
                ephemeral=True,
            )
            return

        removed = await self.database.delete_notification(
            self.guild_id,
            notification_id,
        )
        self.stop()
        await interaction.response.edit_message(
            content=(
                f"✅ Removed **{discord.utils.escape_markdown(notification.name)}**."
                if removed
                else "That notification had already been removed."
            ),
            view=None,
        )


class EditMessageModal(discord.ui.Modal, title="Edit notification messages"):
    message = discord.ui.TextInput(
        label="Active message",
        style=discord.TextStyle.paragraph,
        max_length=MAX_CUSTOM_MESSAGE_LENGTH,
        required=False,
        placeholder=DEFAULT_MESSAGE,
    )
    ended_message = discord.ui.TextInput(
        label="Message when everyone leaves",
        style=discord.TextStyle.paragraph,
        max_length=MAX_CUSTOM_MESSAGE_LENGTH,
        required=False,
        placeholder=DEFAULT_ENDED_MESSAGE,
    )

    def __init__(
        self,
        database: Database,
        guild_id: int,
        notification: Notification,
    ) -> None:
        super().__init__()
        self.database = database
        self.guild_id = guild_id
        self.notification = notification
        self.message.default = notification.message_template
        self.ended_message.default = notification.ended_message_template

    async def on_submit(self, interaction: discord.Interaction) -> None:
        message = str(self.message.value).strip() or DEFAULT_MESSAGE
        ended_message = (
            str(self.ended_message.value).strip() or DEFAULT_ENDED_MESSAGE
        )
        unknown_placeholders = (
            find_unknown_placeholders(message)
            | find_unknown_placeholders(ended_message)
        )
        if unknown_placeholders:
            formatted = ", ".join(f"`{{{item}}}`" for item in unknown_placeholders)
            await interaction.response.send_message(
                f"Unknown message placeholder(s): {formatted}",
                ephemeral=True,
            )
            return

        updated = await self.database.update_messages(
            self.guild_id,
            self.notification.id,
            message,
            ended_message,
        )
        await interaction.response.edit_message(
            content=(
                f"✅ Updated the messages for "
                f"**{discord.utils.escape_markdown(self.notification.name)}**."
                if updated
                else "That notification no longer exists."
            ),
            view=None,
        )


class EditMessageView(NotificationPagedView):
    def __init__(
        self,
        owner_id: int,
        guild_id: int,
        database: Database,
        notifications: list[Notification],
    ) -> None:
        self.guild_id = guild_id
        self.database = database
        super().__init__(owner_id, notifications, "Select a notification to edit")

    async def notification_selected(
        self,
        interaction: discord.Interaction,
        notification_id: int,
    ) -> None:
        notification = await self.database.get_notification(
            self.guild_id,
            notification_id,
        )
        if notification is None:
            await interaction.response.send_message(
                "That notification no longer exists.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            EditMessageModal(self.database, self.guild_id, notification)
        )


class VoicelyRoleBot(commands.Bot):
    def __init__(self, database: Database, dev_guild_id: int | None) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True

        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.database = database
        self.dev_guild_id = dev_guild_id
        self.initialized_states = False

    async def setup_hook(self) -> None:
        await self.database.initialize()
        await self.add_cog(VoicelyRoleCommands(self, self.database))

        if self.dev_guild_id is not None:
            guild_object = discord.Object(id=self.dev_guild_id)
            self.tree.copy_global_to(guild=guild_object)
            synced = await self.tree.sync(guild=guild_object)
            logger.info("Synced %s development command(s).", len(synced))
        else:
            synced = await self.tree.sync()
            logger.info("Synced %s global command(s).", len(synced))

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")
        if not self.initialized_states:
            await self.reconcile_all_trigger_states()
            self.initialized_states = True

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or before.channel == after.channel:
            return

        channels: list[discord.VoiceChannel] = []
        if isinstance(before.channel, discord.VoiceChannel):
            channels.append(before.channel)
        if isinstance(after.channel, discord.VoiceChannel):
            channels.append(after.channel)

        for channel in dict.fromkeys(channels):
            await self.evaluate_voice_channel(channel)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.database.remove_guild(guild.id)

    async def reconcile_all_trigger_states(self) -> None:
        for guild in self.guilds:
            notifications = await self.database.get_notifications(guild.id)
            for notification in notifications:
                channel_ids = await self.database.get_voice_channel_ids(notification.id)
                for channel_id in channel_ids:
                    channel = guild.get_channel(channel_id)
                    if not isinstance(channel, discord.VoiceChannel):
                        continue
                    count = await counted_human_count(channel, self.database)
                    await self.database.set_triggered(
                        notification.id,
                        channel.id,
                        count >= notification.threshold,
                    )

    async def evaluate_voice_channel(self, channel: discord.VoiceChannel) -> None:
        count = await counted_human_count(channel, self.database)
        watched = await self.database.get_notifications_for_voice_channel(
            channel.guild.id,
            channel.id,
        )

        for notification, triggered, message_id in watched:
            if triggered:
                if count == 0:
                    if message_id is not None:
                        await self.edit_notification_message(
                            notification,
                            channel,
                            count,
                            message_id,
                            ended=True,
                        )
                    await self.database.clear_trigger_state(
                        notification.id,
                        channel.id,
                    )
                    continue

                if message_id is not None:
                    await self.edit_notification_message(
                        notification,
                        channel,
                        count,
                        message_id,
                        ended=False,
                    )
                continue

            if count < notification.threshold:
                continue

            await self.database.set_triggered(
                notification.id,
                channel.id,
                True,
            )
            sent_message = await self.send_notification(
                notification,
                channel,
                count,
            )
            if sent_message is not None:
                await self.database.set_message_id(
                    notification.id,
                    channel.id,
                    sent_message.id,
                )

    def render_notification_message(
        self,
        notification: Notification,
        voice_channel: discord.VoiceChannel,
        count: int,
        *,
        ended: bool,
    ) -> str:
        role = voice_channel.guild.get_role(notification.role_id)
        role_mention = role.mention if role is not None else f"<@&{notification.role_id}>"
        template = (
            notification.ended_message_template
            if ended
            else notification.message_template
        )

        try:
            return template.format(
                role=role_mention,
                channel=voice_channel.mention,
                channel_name=voice_channel.name,
                count=count,
                threshold=notification.threshold,
            )
        except (KeyError, ValueError):
            logger.exception(
                "Invalid message template for notification %s",
                notification.id,
            )
            fallback = DEFAULT_ENDED_MESSAGE if ended else DEFAULT_MESSAGE
            return fallback.format(
                role=role_mention,
                channel=voice_channel.mention,
                channel_name=voice_channel.name,
                count=count,
                threshold=notification.threshold,
            )

    async def send_notification(
        self,
        notification: Notification,
        voice_channel: discord.VoiceChannel,
        count: int,
    ) -> discord.Message | None:
        guild = voice_channel.guild
        role = guild.get_role(notification.role_id)
        destination = guild.get_channel(notification.destination_channel_id)

        if role is None:
            logger.warning(
                "Notification %s could not ping deleted role %s.",
                notification.id,
                notification.role_id,
            )
            return None
        if not isinstance(destination, discord.TextChannel):
            logger.warning(
                "Notification %s has missing/non-text destination %s.",
                notification.id,
                notification.destination_channel_id,
            )
            return None

        message = self.render_notification_message(
            notification,
            voice_channel,
            count,
            ended=False,
        )

        try:
            return await destination.send(
                message,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[role],
                    replied_user=False,
                ),
            )
        except discord.Forbidden:
            logger.warning(
                "Cannot send notification %s in channel %s.",
                notification.id,
                destination.id,
            )
        except discord.HTTPException:
            logger.exception("Failed to send notification %s", notification.id)
        return None

    async def edit_notification_message(
        self,
        notification: Notification,
        voice_channel: discord.VoiceChannel,
        count: int,
        message_id: int,
        *,
        ended: bool,
    ) -> None:
        destination = voice_channel.guild.get_channel(
            notification.destination_channel_id
        )
        if not isinstance(destination, discord.TextChannel):
            return

        try:
            message = await destination.fetch_message(message_id)
            await message.edit(
                content=self.render_notification_message(
                    notification,
                    voice_channel,
                    count,
                    ended=ended,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.NotFound:
            logger.warning(
                "The message for notification %s in voice channel %s was deleted.",
                notification.id,
                voice_channel.id,
            )
        except discord.Forbidden:
            logger.warning(
                "Cannot edit notification %s in channel %s.",
                notification.id,
                destination.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to edit notification %s.",
                notification.id,
            )


class VoicelyRoleCommands(commands.Cog):
    group = app_commands.Group(
        name="voicely-role",
        description="Configure voice-channel role notifications.",
        guild_only=True,
    )

    def __init__(self, bot: VoicelyRoleBot, database: Database) -> None:
        self.bot = bot
        self.database = database

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        logger.error("Application command error", exc_info=error)
        message = "Something went wrong while running that command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def require_manager(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return False

        if interaction.user.guild_permissions.administrator:
            return True

        admin_role_ids = await self.database.get_admin_role_ids(interaction.guild.id)
        if any(role.id in admin_role_ids for role in interaction.user.roles):
            return True

        await interaction.response.send_message(
            "You need a configured Voicely Role admin role or Discord Administrator permission.",
            ephemeral=True,
        )
        return False

    @group.command(name="add", description="Create a voice-channel role notification.")
    async def add(self, interaction: discord.Interaction) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None
        view = AddNotificationView(
            interaction.user.id,
            interaction.guild,
            self.database,
        )
        await interaction.response.send_message(
            view.summary(),
            view=view,
            ephemeral=True,
        )

    @group.command(name="remove", description="Remove a saved notification.")
    async def remove(self, interaction: discord.Interaction) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None
        notifications = await self.database.get_notifications(interaction.guild.id)
        if not notifications:
            await interaction.response.send_message(
                "This server has no saved notifications.",
                ephemeral=True,
            )
            return

        view = RemoveNotificationView(
            interaction.user.id,
            interaction.guild.id,
            self.database,
            notifications,
        )
        await interaction.response.send_message(
            "Select the notification you want to remove.",
            view=view,
            ephemeral=True,
        )

    @group.command(name="list", description="List this server's notifications.")
    async def list_notifications(self, interaction: discord.Interaction) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None
        notifications = await self.database.get_notifications(interaction.guild.id)
        if not notifications:
            await interaction.response.send_message(
                "This server has no saved notifications.",
                ephemeral=True,
            )
            return

        embeds: list[discord.Embed] = []
        current = discord.Embed(title="Voicely Role notifications")
        field_count = 0

        for notification in notifications:
            channel_ids = await self.database.get_voice_channel_ids(notification.id)
            voice_channels = ", ".join(f"<#{channel_id}>" for channel_id in channel_ids)
            value = (
                f"**Threshold:** {notification.threshold}\n"
                f"**Role:** <@&{notification.role_id}>\n"
                f"**Sends in:** <#{notification.destination_channel_id}>\n"
                f"**Voice channels:** {voice_channels}\n"
                f"**Active message:** {discord.utils.escape_markdown(notification.message_template)}\n"
                f"**Everyone-left message:** "
                f"{discord.utils.escape_markdown(notification.ended_message_template)}"
            )

            if field_count == 25 or len(current) + len(value) > 5500:
                embeds.append(current)
                current = discord.Embed(title="Voicely Role notifications (continued)")
                field_count = 0

            current.add_field(
                name=f"{notification.name} (ID {notification.id})"[:256],
                value=value[:1024],
                inline=False,
            )
            field_count += 1

        embeds.append(current)
        await interaction.response.send_message(embeds=embeds[:10], ephemeral=True)

    @group.command(
        name="edit-message",
        description="Change a saved notification's active and everyone-left messages.",
    )
    async def edit_message(self, interaction: discord.Interaction) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None
        notifications = await self.database.get_notifications(interaction.guild.id)
        if not notifications:
            await interaction.response.send_message(
                "This server has no saved notifications.",
                ephemeral=True,
            )
            return

        view = EditMessageView(
            interaction.user.id,
            interaction.guild.id,
            self.database,
            notifications,
        )
        await interaction.response.send_message(
            "Select the notification whose messages you want to edit.",
            view=view,
            ephemeral=True,
        )

    @group.command(
        name="exclude-user",
        description="Exclude a user from all voice-channel counts.",
    )
    @app_commands.describe(user="The user to exclude from threshold counts")
    async def exclude_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None

        added = await self.database.exclude_user(interaction.guild.id, user.id)
        await interaction.response.send_message(
            (
                f"✅ {user.mention} is now excluded from Voicely Role counts."
                if added
                else f"{user.mention} was already excluded."
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        if user.voice is not None and isinstance(
            user.voice.channel,
            discord.VoiceChannel,
        ):
            await self.bot.evaluate_voice_channel(user.voice.channel)

    @group.command(
        name="include-user",
        description="Include a previously excluded user in counts again.",
    )
    @app_commands.describe(user="The excluded user to count again")
    async def include_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None

        removed = await self.database.include_user(interaction.guild.id, user.id)
        await interaction.response.send_message(
            (
                f"✅ {user.mention} will now count toward thresholds."
                if removed
                else f"{user.mention} was not excluded."
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        if user.voice is not None and isinstance(
            user.voice.channel,
            discord.VoiceChannel,
        ):
            await self.bot.evaluate_voice_channel(user.voice.channel)

    @group.command(
        name="excluded-users",
        description="List users excluded from voice-channel counts.",
    )
    async def excluded_users(self, interaction: discord.Interaction) -> None:
        if not await self.require_manager(interaction):
            return
        assert interaction.guild is not None

        user_ids = await self.database.get_excluded_user_ids(interaction.guild.id)
        if not user_ids:
            await interaction.response.send_message(
                "This server has no excluded users.",
                ephemeral=True,
            )
            return

        mentions = "\n".join(f"• <@{user_id}>" for user_id in sorted(user_ids))
        await interaction.response.send_message(
            f"**Excluded users:**\n{mentions}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @group.command(
        name="admin-roles",
        description="Choose roles allowed to manage Voicely Role.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_roles(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        current_ids = await self.database.get_admin_role_ids(interaction.guild.id)
        current = ", ".join(f"<@&{role_id}>" for role_id in current_ids) or "None"
        view = AdminRolesView(
            interaction.user.id,
            interaction.guild.id,
            self.database,
        )
        await interaction.response.send_message(
            f"**Current Voicely Role admin roles:** {current}\n"
            "Select the complete new set below, or use the clear button.",
            view=view,
            ephemeral=True,
        )

    @admin_roles.error
    async def admin_roles_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Only someone with Discord's Administrator permission can change admin roles.",
                ephemeral=True,
            )
            return
        raise error


ALLOWED_PLACEHOLDERS = {
    "role",
    "channel",
    "channel_name",
    "count",
    "threshold",
}


def find_unknown_placeholders(template: str) -> set[str]:
    import string

    unknown: set[str] = set()
    try:
        for _, field_name, _, _ in string.Formatter().parse(template):
            if field_name and field_name not in ALLOWED_PLACEHOLDERS:
                unknown.add(field_name)
    except ValueError:
        unknown.add("invalid formatting")
    return unknown


async def counted_human_count(
    channel: discord.VoiceChannel,
    database: Database,
) -> int:
    excluded_user_ids = await database.get_excluded_user_ids(channel.guild.id)
    return sum(
        1
        for member in channel.members
        if not member.bot and member.id not in excluded_user_ids
    )


def read_optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise RuntimeError("DEV_GUILD_ID must be a numeric Discord server ID.") from exc


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Copy .env.example to .env and enter the bot token."
        )

    dev_guild_id = read_optional_int(os.getenv("DEV_GUILD_ID"))
    database = Database(DATABASE_PATH)
    bot = VoicelyRoleBot(database, dev_guild_id)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
