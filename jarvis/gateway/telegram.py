"""Telegram gateway — message your laptop from your phone.

Setup (2 minutes, free):
  1. In Telegram, message @BotFather → /newbot → copy the token
  2. Put TELEGRAM_BOT_TOKEN=... in .env
  3. Optionally set TELEGRAM_ALLOWED_USER=<your numeric id> (message
     @userinfobot to get it) so ONLY you can talk to your Jarvis
  4. make telegram

Long-polling: your laptop calls Telegram's API — no public URL, no webhook,
no server. This is why hobbyist assistants pick Telegram over WhatsApp
(Meta's Cloud API needs business verification and a public HTTPS endpoint).
"""

from __future__ import annotations

import os

from jarvis.app import Jarvis
from jarvis.gateway.cli import _observer  # mirror gate/tool activity on the laptop terminal


def main() -> None:
    try:
        from telegram import Update
        from telegram.ext import Application, ContextTypes, MessageHandler, filters
    except ImportError:
        raise SystemExit("Telegram extra not installed: pip install 'launch-jarvis[telegram]'")

    jarvis = Jarvis()
    token = jarvis.settings.telegram_token
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (message @BotFather to create a bot).")
    allowed = os.getenv("TELEGRAM_ALLOWED_USER", "")

    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if allowed and str(update.effective_user.id) != allowed:
            await update.message.reply_text("This Jarvis serves someone else. Run your own!")
            return
        print(f"you › {update.message.text}")
        result = jarvis.respond(update.message.text, observer=_observer)
        print(f"jarvis › {result.reply}")
        await update.message.reply_text(result.reply or "(no reply)")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("Jarvis is listening on Telegram — message your bot. Ctrl-C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
