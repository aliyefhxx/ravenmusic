# main.py - Raven Music Userbot ana faylı
import asyncio
import logging
import os
import uuid
import threading

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from keep_alive import app as fastapi_app
from player import RavenPlayer, queues, now_playing, control_messages, get_control_keyboard

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("RavenMusic")

# ── Env dəyişənləri ──────────────────────────────────────────────
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
PORT = int(os.environ.get("PORT", 8000))

# ── Pyrogram Client ───────────────────────────────────────────────
userbot = Client(
    "raven_music",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ── Player ────────────────────────────────────────────────────────
player: RavenPlayer | None = None


# ═══════════════════════════════════════════════════════════════════
#  KOMANDALAR
# ═══════════════════════════════════════════════════════════════════

@userbot.on_message(filters.command("play", prefixes=".") & (filters.group | filters.channel))
async def play_command(client: Client, message: Message):
    """
    .play mahnı adı
    """
    if len(message.command) < 2:
        await message.reply("🎵 İstifadə: `.play mahnı adı`")
        return

    song_name = " ".join(message.command[1:])
    chat_id = message.chat.id
    requested_by = message.from_user.first_name if message.from_user else "Naməlum"

    # Queue dolubsa xəbərdarlıq
    if len(queues[chat_id]) >= 10:
        await message.reply("⚠️ Queue doludur! Maksimum 10 mahnı.")
        return

    status_msg = await message.reply(f"🔍 **{song_name}** axtarılır...")

    request_id = str(uuid.uuid4())[:8]

    success = await player.add_to_queue(
        client,
        chat_id,
        song_name,
        request_id,
        requested_by
    )

    if success:
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        await status_msg.edit(
            f"❌ **{song_name}** tapılmadı və ya yüklənmədi."
        )


@userbot.on_message(filters.command("end", prefixes=".") & (filters.group | filters.channel))
async def end_command(client: Client, message: Message):
    """.end - oxumanı dayandır"""
    chat_id = message.chat.id

    if chat_id not in now_playing:
        await message.reply("🔇 Hazırda heç nə oxunmur.")
        return

    await player.end(chat_id)
    await message.reply("⏹ Oxuma dayandırıldı, səsli chatdan çıxıldı.")


# ═══════════════════════════════════════════════════════════════════
#  INLINE BUTTON CALLBACKLAR
# ═══════════════════════════════════════════════════════════════════

@userbot.on_callback_query()
async def callback_handler(client: Client, query: CallbackQuery):
    data = query.data

    if data.startswith("pause_"):
        chat_id = int(data.split("_")[1])
        is_paused = await player.pause(chat_id)
        keyboard = await get_control_keyboard(chat_id, paused=is_paused)
        try:
            await query.message.edit_reply_markup(keyboard)
        except Exception:
            pass
        status = "⏸ Durduruldu" if is_paused else "▶️ Davam edir"
        await query.answer(status)

    elif data.startswith("skip_"):
        chat_id = int(data.split("_")[1])
        await player.skip(chat_id)
        await query.answer("⏭ Keçildi")

    elif data.startswith("prev_"):
        chat_id = int(data.split("_")[1])
        await player.prev(chat_id)
        await query.answer("⏮ Əvvəlki")

    elif data.startswith("end_"):
        chat_id = int(data.split("_")[1])
        await player.end(chat_id)
        await query.answer("⏹ Dayandırıldı")

    elif data.startswith("close_"):
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer("❌ Bağlandı")


# ═══════════════════════════════════════════════════════════════════
#  SESSION STRING YARATMAQ (ilk dəfə)
# ═══════════════════════════════════════════════════════════════════

async def generate_session():
    """Əgər SESSION_STRING yoxdursa, yeni session yarat"""
    async with Client(
        "session_gen",
        api_id=API_ID,
        api_hash=API_HASH,
    ) as app:
        session = await app.export_session_string()
        print(f"\n✅ SESSION_STRING:\n{session}\n")


# ═══════════════════════════════════════════════════════════════════
#  ANA FUNKSIYA
# ═══════════════════════════════════════════════════════════════════

async def start_userbot():
    global player
    await userbot.start()
    player = RavenPlayer(userbot)
    await player.start()
    logger.info("🎵 Raven Music Userbot işə düşdü!")

    # FastAPI-ni ayrı thread-də işlət
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        userbot.idle()
    )


if __name__ == "__main__":
    # SESSION_STRING yoxdursa generate et
    if not os.environ.get("SESSION_STRING"):
        asyncio.run(generate_session())
    else:
        asyncio.run(start_userbot())
