# Voicely Role

Voicely Role watches selected Discord voice channels and pings a selected role when a configured number of non-bot users is reached.

Each notification/channel pair is independent. This allows several notifications on the same voice channel, such as:

- 2 users: ping `@Casual Players`
- 4 users: ping `@Gaming`
- 8 users: ping `@Large Group`

After a notification triggers for a voice channel, that notification will not trigger there again until the channel becomes completely empty.

## Commands

- `/voicely-role add` — Create a notification with dropdowns and a details modal.
- `/voicely-role remove` — Select and remove a saved notification.
- `/voicely-role list` — List saved notifications.
- `/voicely-role edit-message` — Change a notification's custom message.
- `/voicely-role admin-roles` — Select roles allowed to manage notifications. Requires Discord Administrator permission.

Discord Administrators can always manage notifications.

## Setup

1. Install Python 3.11 or newer.
2. Create a Discord application and bot in the Discord Developer Portal.
3. Under **Bot**, enable **Server Members Intent**. Voice State intent is non-privileged and is requested by the code.
4. Invite the bot with these scopes:
   - `bot`
   - `applications.commands`
5. Give the bot these server/channel permissions:
   - View Channels
   - Send Messages
   - Embed Links
   - Mention Everyone (needed to reliably mention roles that are not configured as mentionable)
6. Copy `.env.example` to `.env`, then enter the bot token.
7. Install dependencies and run the bot:

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Message placeholders

Custom messages support:

- `{role}` — role mention
- `{channel}` — voice channel mention
- `{channel_name}` — voice channel name without a mention
- `{count}` — current number of non-bot users
- `{threshold}` — configured threshold

Default message:

```text
🔊 {role} There are now **{count} people** in {channel}!
```

## Restart behavior

When the bot starts:

- Empty watched channels are re-armed.
- Occupied channels below a notification's threshold remain armed and can trigger when the threshold is reached.
- Occupied channels already at or above the threshold are marked as triggered without sending a startup ping.

Settings are stored in `voicely-role.db`.
