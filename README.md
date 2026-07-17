[![Invite Me](https://img.shields.io/badge/Invite%20Me-7965c7?style=for-the-badge)](https://discord.com/oauth2/authorize?client_id=1527731147428073493)
<br>
[![Our Discord](https://img.shields.io/discord/1102582171207741480?style=for-the-badge&logo=discord&logoColor=ffffff&label=Our%20Discord&color=5865F2)](https://discord.gozarproductions.com)
[![Our Other Projects](https://img.shields.io/badge/Our%20Other%20Projects-%E2%9D%A4-563294?style=for-the-badge&logo=data%3Aimage%2Fwebp%3Bbase64%2CUklGRu4DAABXRUJQVlA4WAoAAAAQAAAAHwAAHwAAQUxQSGABAAABgFtbm5volyZTA%2BtibzK2H0w5sDkmhe3GmxrwxGg0839r%2FvkkOogIBW7bKB0c4%2BARYihzIqfd6dfO%2B%2B3XtHsq4jJhlIvcDRcgNB%2FeieQETorBHgghRtUYqwDs%2B4U4IpcvUB%2BVUPSK54uEnTwsUJoar2DeMpzLxQpeG5DH8lxyyfLivVYAwPBbkWdOBg3qFlqiLy679iHy9UDKMZRXmYxpCcusayTHG01K%2FEtatYWuj7oI9hL4BxsxVwhoP2mlAJJ%2BuuAflc6%2BEUCQTCX9EV87xBR2H75NxLZSpWiwzqdIm7ZO7uB3oEgZKbD9Nt3EmHweEPH1t1GNsZUbKeisiwjyTm5fA3SO1yCrADZXrV2PZQJPL1tjN4%2BxUL9ie1mJobzOnDwSx6ILiF%2FW%2BTUR4tcHx0UaV75JXC1a4g6Ky5dLcTSuy9q4HhTieF64Hy1A3GHB8gLLK2e92feuqnbfPK8IVlA4IGgCAACwDQCdASogACAAPk0cjEQioaEb%2BqwAKATEtgBOl7v9V3sHcA2wG4A3gD0APLP9jX9n%2F2jmqv5AZRh7J%2BN2fOx22iE%2F4TUsecFmY%2BSf1r%2BAP%2BTfzT%2FXdIB7KX7MtdIGr1A8H0jmrrfZvqButwOaYcLWYNRq5QgAAP7%2F%2FmIMpiVNn67QXpM1rrDmRS8Nr%2F6dhD%2Bq5e%2BM%2BAtUP1%2FxOj85Ol5y3ebjz%2BpHoOf%2FWW8a%2F2ojUaKVDkVqof%2Bv4f0f6ud8i58wusz%2Fyrj%2F%2BwnM3q0769dvK%2F%2BQe04xL49tkb9t6ylCqqezZtZGuGLJ%2F5iUrPqdYc%2F8VbYZfP%2FOpZP%2F4X4q%2BqS4gPOxzdINOe5PGv%2F0TS%2FJRf4LlFrFkrWtxlS8n40grV%2BKUu%2FiwzdQzImvwH81FxL1bZyTSsrYwMku1Pk9StTtWNjSR8ZWEYBH9eTn%2FvBERii5XaWOPJ%2FFVXtVQGbv%2BFRW5jbo9tfFDu%2BDHHf8LbgUd%2F8W8Id1AehBtRNsLQWbADmvF1QJU8x5tw%2FtTUwIoSaa%2F2jkcvyVHkAsb2qoIh1KF1pPdae%2BZaqjydy6nUa9agjrDk1G4pMhEUhH%2BV%2FIUe49MjhR%2FuxyFmwQ8dDogMyQ%2BdcSBa56Lwt1wyJ%2F22%2F5O98r6q6wiM63HyaYONd36W7br%2F0%2F6y2DZ3irAddj%2FRxntvr%2FbbChSYXAfEbO%2FD0G%2FFbMFqTHypodt9T6dAx%2BUjJYfHzFf%2FM3Ec%2FAtwbjc2gka6urN1MlSLb2VTS9Q5r8fkDzxZz6vu1OYUPUB1UFMIhYGvMATbxxoTmVhvpovzAc%2F8nbOjw3wAAA)](https://github.com/Erallie)
[![Donate](https://img.shields.io/badge/Donate-%24-563294?style=for-the-badge&logo=ko-fi&logoColor=FFFFFF&color=FF6433)](https://www.ko-fi.com/GozarProductions)

---

# Voicely Role

Voicely Role watches selected Discord voice channels and pings a selected role when a configured number of counted, non-bot users is reached. Server managers can exclude specific users from all threshold counts.

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
- `/voicely-role exclude-user user:@User` — Exclude a mentioned user from all threshold counts.
- `/voicely-role include-user user:@User` — Make an excluded user count again.
- `/voicely-role excluded-users` — List the server's excluded users.
- `/voicely-role admin-roles` — Select roles allowed to manage notifications. Requires Discord Administrator permission.

Discord Administrators can always manage notifications. The configured Voicely Role admin roles can also add, remove, list, and edit notifications and manage excluded users.

## Invite

Invite Voicely Role to your server using [this invite link](https://discord.com/oauth2/authorize?client_id=1527731147428073493)!

## Message placeholders

Custom messages support:

- `{role}` — role mention
- `{channel}` — voice channel mention
- `{channel_name}` — voice channel name without a mention
- `{count}` — current number of counted, non-bot users
- `{threshold}` — configured threshold

Default message:

```text
🔊 {role} There are now **{count} people** in {channel}!
```

## Excluded users

Excluded users are ignored for every notification in the server. For example, if a voice channel contains two regular users and one excluded user, its count is `2`. This is useful if you have alt accounts that you use the join voice channels.

An excluded user also does not keep a notification armed. If all counted users leave and only excluded users remain, the effective count is zero and notifications for that channel re-arm. Use the slash command's `user` field to type or paste an `@mention`.

## Restart behavior

When the bot starts:

- Empty watched channels are re-armed.
- Occupied channels below a notification's threshold remain armed and can trigger when the threshold is reached.
- Occupied channels already at or above the threshold are marked as triggered without sending a startup ping.

Settings are stored in `voicely-role.db`.
