# Discord Guss / LoB MSM

MapleStory M Discord bot helpers for community luck checks and official patch-note announcements.

## Language

**Patch Note**:
A forum thread on the official Thai MapleStory M patch-notes board that the bot watches for announcements.
_Avoid_: news post, update, announcement (when referring to the forum source)

**Announcement**:
A single Discord channel message that informs members about one newly seen Patch Note.
_Avoid_: notify, alert, broadcast

**Voice Monitor**:
The bot's live relay of a Discord voice channel's mixed audio to the admin web dashboard. Nothing is stored on the server; an admin's browser can save a local WAV while listening.
_Avoid_: wiretap

**Listener**:
An authenticated admin browser session connected to the Voice Monitor stream.
_Avoid_: viewer, client

**Seen Patch Note**:
A Patch Note the bot has already recorded, so it must never produce another Announcement for that same identity.
_Avoid_: cached post, processed thread
