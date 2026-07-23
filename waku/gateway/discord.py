"""Discord gateway — message Waku from a Discord server or direct message.

Setup:
  1. Create a bot at https://discord.com/developers/applications
  2. Enable the Message Content Intent on the bot page
  3. Put DISCORD_BOT_TOKEN=... in .env and invite the bot to your server
  4. Optionally set DISCORD_ALLOWED_USER=<your numeric Discord user id>
  5. make discord
"""

from __future__ import annotations

import os

from waku.app import Waku
from waku.gateway.cli import _observer


def _build_client(allowed: str):
    """Build the Discord client and its message handler."""
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    waku = Waku()
    waku.session.session_id = "discord"

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author == client.user:
            return
        if allowed and str(message.author.id) != allowed:
            await message.reply("This Waku serves someone else. Run your own!")
            return
        if not message.content:
            return
        print(f"you › {message.content}")
        async with message.channel.typing():
            result = waku.respond(message.content, observer=_observer, source="discord")
        print(f"waku › {result.reply}")
        await message.reply(result.reply or "(no reply)")

    return client


def main() -> None:
    try:
        import discord  # noqa: F401
    except ImportError:
        raise SystemExit("Discord extra not installed: pip install 'waku-agent[discord]'")

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN in .env (create a bot in the Discord Developer Portal).")
    client = _build_client(os.getenv("DISCORD_ALLOWED_USER", ""))
    print("Waku is listening on Discord — message your bot. Ctrl-C to stop.")
    client.run(token)


def start_in_background() -> bool:
    """Start Discord on a daemon thread, returning False when it is not configured."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        return False
    try:
        import discord  # noqa: F401
    except ImportError:
        print("(discord) DISCORD_BOT_TOKEN is set but the extra isn't installed — "
              "pip install 'waku-agent[discord]'")
        return False

    import threading

    allowed = os.getenv("DISCORD_ALLOWED_USER", "")

    def run() -> None:
        try:
            _build_client(allowed).run(token)
        except Exception as exc:  # noqa: BLE001 — isolate the dashboard from bot errors
            print(f"(discord) background client stopped: {exc}")

    threading.Thread(target=run, daemon=True, name="discord-client").start()
    return True


if __name__ == "__main__":
    main()