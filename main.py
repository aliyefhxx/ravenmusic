# main.py - Raven Music Ana Faylı (Yedək Komanda və Əlavə Bot Rejimi)
import asyncio
import logging
import os
import uuid

import uvicorn
from dotenv import load_dotenv

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from keep_alive import app as fastapi_app
from player import RavenPlayer, queues, now_playing, control_messages, get_control_keyboard

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("RavenMusic")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", 8000))

BOT_USERNAME = "@RavenMscUserbot"  # Avtomatik dəvət üçün botun istifadəçi adı

userbot = TelegramClient(StringSession(SESSION_STRING), api_id=API_ID, api_hash=API_HASH)
tg_bot = TelegramClient("raven_bot_session", api_id=API_ID, api_hash=API_HASH)
player: RavenPlayer | None = None


# ═══════════════════════════════════════════════════════════════════
#  MƏTNƏ ƏSASLANAN YEDƏK KOMANDALAR (Düymə işləməyən qruplar üçün)
# ═══════════════════════════════════════════════════════════════════

@userbot.on(events.NewMessage(pattern=r"^\.play(?:\s+(.+))?"))
async def play_command(event: events.NewMessage.Event):
    song_name = event.pattern_match.group(1)
    if not song_name:
        await event.respond("🎵 İstifadə: `.play mahnı adı`")
        return

    chat_id = event.chat_id
    sender = await event.get_sender()
    requested_by = getattr(sender, 'first_name', 'Naməlum') if sender else "Naməlum"

    if len(queues[chat_id]) >= 10:
        await event.respond("⚠️ Növbə doludur! Maksimum 10 mahnı.")
        return

    status_msg = await event.respond(f"🔍 **{song_name}** axtarılır...")
    request_id = str(uuid.uuid4())[:8]

    success = await player.add_to_queue(userbot, chat_id, song_name, request_id, requested_by)

    if success:
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        await status_msg.edit(f"❌ **{song_name}** tapılmadı.")


@userbot.on(events.NewMessage(pattern=r"^\.end"))
async def end_command(event: events.NewMessage.Event):
    """Mahnını və səsli çatı tam dayandırır"""
    chat_id = event.chat_id
    if chat_id not in now_playing:
        await event.respond("🔇 Hazırda heç nə oxunmur.")
        return
    await player.end(chat_id)
    await event.respond("⏹ Oxuma dayandırıldı, səsli çatdan çıxıldı.")


@userbot.on(events.NewMessage(pattern=r"^\.skip"))
async def skip_command(event: events.NewMessage.Event):
    """Növbəti mahnıya keçir"""
    chat_id = event.chat_id
    if chat_id not in now_playing:
        await event.respond("🔇 Hazırda oxunacaq mahnı yoxdur.")
        return
    await player.skip(chat_id)
    await event.respond("⏭ Növbəti mahnıya keçildi.")


@userbot.on(events.NewMessage(pattern=r"^\.pause"))
async def pause_command(event: events.NewMessage.Event):
    """Mahnını anlıq saxlayır"""
    chat_id = event.chat_id
    if chat_id not in now_playing:
        return
    await player.pause(chat_id)
    await event.respond("⏸ Mahnı durduruldu. Davam etmək üçün: `.resume`")


@userbot.on(events.NewMessage(pattern=r"^\.resume"))
async def resume_command(event: events.NewMessage.Event):
    """Mahnını davam etdirir"""
    chat_id = event.chat_id
    if chat_id not in now_playing:
        return
    await player.pause(chat_id)
    await event.respond("▶️ Mahnı davam etdirilir.")


# ═══════════════════════════════════════════════════════════════════
#  DÜYMƏ CALLBACK SİSTEMİ
# ═══════════════════════════════════════════════════════════════════

@tg_bot.on(events.CallbackQuery)
async def callback_handler(event: events.CallbackQuery.Event):
    data = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data
    chat_id = event.chat_id

    if data.startswith("pause_"):
        is_paused = await player.pause(chat_id)
        keyboard = await get_control_keyboard(chat_id, paused=is_paused)
        try:
            await event.edit(buttons=keyboard)
        except Exception:
            pass
        await event.answer("⏸ Durduruldu" if is_paused else "▶️ Davam edir")

    elif data.startswith("skip_"):
        await player.skip(chat_id)
        await event.answer("⏭ Keçildi")

    elif data.startswith("end_"):
        await player.end(chat_id)
        await event.answer("⏹ Dayandırıldı")

    elif data.startswith("close_"):
        try:
            await event.delete()
        except Exception:
            pass
        await event.answer("❌ Bağlandı")


# ═══════════════════════════════════════════════════════════════════
#  SİSTEMİ BAŞLATMAQ
# ═══════════════════════════════════════════════════════════════════

async def start_userbot():
    global player
    await userbot.start()
    await tg_bot.start(bot_token=BOT_TOKEN)
    
    player = RavenPlayer(userbot, bot_client=tg_bot)
    await player.start()
    
    logger.info("🎵 Raven Music Bot Sistemi Aktivdir!")

    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=PORT, log_level="warning")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        userbot.run_until_disconnected(),
        tg_bot.run_until_disconnected()
    )


if __name__ == "__main__":
    asyncio.run(start_userbot())
