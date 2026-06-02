# main.py - Raven Music (Userbot + Bot Token Birgə İşlək Versiya)
import asyncio
import logging
import os
import uuid

import uvicorn
from dotenv import load_dotenv

# Telethon importları
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

# ── Env dəyişənləri ──────────────────────────────────────────────
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
BOT_TOKEN = os.environ["BOT_TOKEN"]  # Sənin əlavə etdiyin Bot Token
PORT = int(os.environ.get("PORT", 8000))

# ── Telethon Userbot Client (Səsə girmək üçün) ────────────────────
userbot = TelegramClient(
    StringSession(SESSION_STRING),
    api_id=API_ID,
    api_hash=API_HASH,
)

# ── Telethon Bot Client (Düymələrin kliklənməsi üçün) ─────────────
# Bot tokeni daxil edirik ki, inline button xətası tamamilə həll olunsun
tg_bot = TelegramClient(
    "raven_bot_session",
    api_id=API_ID,
    api_hash=API_HASH
)

# ── Player ────────────────────────────────────────────────────────
player: RavenPlayer | None = None


# ═══════════════════════════════════════════════════════════════════
#  KOMANDALAR (Userbot qrupda yazılanları dinləyir)
# ═══════════════════════════════════════════════════════════════════

@userbot.on(events.NewMessage(pattern=r"^\.play(?:\s+(.+))?"))
async def play_command(event: events.NewMessage.Event):
    """
    .play mahnı adı
    """
    song_name = event.pattern_match.group(1)
    if not song_name:
        await event.respond("🎵 İstifadə: `.play mahnı adı`")
        return

    chat_id = event.chat_id
    
    # Göndərən şəxsin adını təyin edirik
    sender = await event.get_sender()
    requested_by = "Naməlum"
    if sender:
        requested_by = getattr(sender, 'first_name', 'Naməlum')

    # Queue dolubsa xəbərdarlıq
    if len(queues[chat_id]) >= 10:
        await event.respond("⚠️ Queue doludur! Maksimum 10 mahnı.")
        return

    status_msg = await event.respond(f"🔍 **{song_name}** axtarılır...")
    request_id = str(uuid.uuid4())[:8]

    # Telethon client-ı (userbot) pleyerə ötürülür
    success = await player.add_to_queue(
        userbot,
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


@userbot.on(events.NewMessage(pattern=r"^\.end"))
async def end_command(event: events.NewMessage.Event):
    """.end - oxumanı dayandır"""
    chat_id = event.chat_id

    if chat_id not in now_playing:
        await event.respond("🔇 Hazırda heç nə oxunmur.")
        return

    await player.end(chat_id)
    await event.respond("⏹ Oxuma dayandırıldı, səsli chatdan çıxıldı.")


# ═══════════════════════════════════════════════════════════════════
#  INLINE BUTTON CALLBACKLAR (Bot Token vasitəsilə idarə olunur)
# ═══════════════════════════════════════════════════════════════════

# QEYD: Düymə kliklərini artıq userbot yox, tg_bot qəbul edir. 
# Bu, Telegram-ın təhlükəsizlik qaydasıdır.
@tg_bot.on(events.CallbackQuery)
async def callback_handler(event: events.CallbackQuery.Event):
    data = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data

    if data.startswith("pause_"):
        chat_id = int(data.split("_")[1])
        is_paused = await player.pause(chat_id)
        keyboard = await get_control_keyboard(chat_id, paused=is_paused)
        try:
            await event.edit(buttons=keyboard)
        except Exception:
            pass
        status = "⏸ Durduruldu" if is_paused else "▶️ Davam edir"
        await event.answer(status)

    elif data.startswith("skip_"):
        chat_id = int(data.split("_")[1])
        await player.skip(chat_id)
        await event.answer("⏭ Keçildi")

    elif data.startswith("prev_"):
        chat_id = int(data.split("_")[1])
        await player.prev(chat_id)
        await event.answer("⏮ Əvvəlki")

    elif data.startswith("end_"):
        chat_id = int(data.split("_")[1])
        await player.end(chat_id)
        await event.answer("⏹ Dayandırıldı")

    elif data.startswith("close_"):
        try:
            await event.delete()
        except Exception:
            pass
        await event.answer("❌ Bağlandı")


# ═══════════════════════════════════════════════════════════════════
#  ANA FUNKSIYA
# ═══════════════════════════════════════════════════════════════════

async def start_userbot():
    global player
    
    # 1. Həm userbotu, həm köməkçi botu eyni anda başladırıq
    await userbot.start()
    await tg_bot.start(bot_token=BOT_TOKEN)
    
    # Player daxilinə köməkçi botu da veririk ki, düyməli mesajları bot ata bilsin
    # Bunun üçün player.py-dakı client-ı tg_bot edə bilərik, amma əsas əmrlər userbotdadır.
    # Pleyeri userbot ilə başladırıq
    player = RavenPlayer(userbot)
    await player.start()
    
    logger.info("🎵 Raven Music Userbot (Telethon) işə düşdü!")
    logger.info("🤖 Köməkçi Bot (Düymələr üçün) aktivləşdirildi!")

    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    # Üçünü də eyni anda paralel icra edirik
    await asyncio.gather(
        server.serve(),
        userbot.run_until_disconnected(),
        tg_bot.run_until_disconnected()
    )


if __name__ == "__main__":
    asyncio.run(start_userbot())
