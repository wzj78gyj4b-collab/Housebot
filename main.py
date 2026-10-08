import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from dotenv import load_dotenv
from house_ai import process_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: Message):
    analysis = await process_message(message.text)

    if not analysis.get("is_safe", True):
        try:
            await message.delete()
            warning = await message.answer(
                f"⚠️ {message.from_user.full_name}, dein geistiger Dünnschiss wurde gerade entsorgt. "
                "Such dir ein Hobby, das weniger Nerven kostet."
            )
            await asyncio.sleep(6)
            await warning.delete()
            return
        except Exception as e:
            logging.error(f"Konnte Nachricht nicht löschen (Fehlen Admin-Rechte?): {e}")

    is_private = message.chat.type == "private"
    is_mentioned = bot.me.username and f"@{bot.me.username}" in message.text

    if is_private or is_mentioned:
        reply_text = analysis.get("reply")
        if reply_text:
            await message.answer(reply_text)

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer(
        "Was willst du? Ich bin Housebot. Wenn du eine brillante Diagnose brauchst, "
        "verschone mich lieber direkt mit deinen Symptomen, weil du ohnehin lügst. "
        "Schreib dein Anliegen oder lass es bleiben."
    )

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Housebot läuft und verachtet den Chat...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
