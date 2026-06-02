# main.py - Raven Music (Userbot + Bot Token Tam Hazır və İnteqrasiyalı Versiya)
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
BOT_TOKEN = os.environ["BOT_TOKEN"]  # Render və ya .env daxilindəki Bot Token
PORT = int(os.environ.get("PORT", 8000))

# ── Telethon Userbot Client (Səsli çata qoşulmaq üçün) ────────────
userbot = TelegramClient(
    StringSession(SESSION_STRING),
    api_id=API_ID,
    api_hash=API_HASH,
)

# ── Telethon Bot Client (İnline düymələri chata göndərib oxumaq üçün) ──
tg_bot = TelegramClient(
    "raven_bot_session",
    api_id=API_ID,
    api_hash=API_HASH
)

# ── Player ────────────────────────────────────────────────────────
player: RavenPlayer | None = None


# ═══════════════════════════════════════════════════════════════════
#  KOMANDALAR (Userbot qrupdakı yazışmaları dinləyir)
# ═══════════════════════════════════════════════════════════════════

@userbot.on(events.NewMessage(pattern=r"^\.play(?:\s+(.+))?"))
async def play_command(event: events.NewMessage.Event):
    """
    .play mahnı adı (Qrupda hər kəs yaza bilər)
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

    # Queue dolubsa xəbərdarlıq (Maksimum 10 mahnı)
    if len(queues[chat_id]) >= 10:
        await event.respond("⚠️ Növbə (Queue) doludur! Maksimum 10 mahnı əlavə edilə bilər.")
        return

    status_msg = await event.respond(f"🔍 **{song_name}** axtarılır və yüklənir...")
    request_id = str(uuid.uuid4())[:8]

    # Həm yükləmə prosesini başladır, həm də pleyerə qoşulur
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
            f"❌ **{song_name}** tapılmadı və ya yüklənmə xətası baş verdi."
        )


@userbot.on(events.NewMessage(pattern=r"^\.end"))
async def end_command(event: events.NewMessage.Event):
    """.end - səsli çatdan tamamilə çıxış və təmizləmə"""
    chat_id = event.chat_id

    if chat_id not in now_playing:
        await event.respond("🔇 Hazırda səsli çatda aktiv mahnı oxunmur.")
        return

    await player.end(chat_id)
    await event.respond("⏹ Oxuma dayandırıldı, növbə təmizləndi və səsli çatdan çıxıldı.")


# ═══════════════════════════════════════════════════════════════════
#  INLINE BUTTON CALLBACKLAR (Köməkçi Bot tərəfindən idarə olunur)
# ═══════════════════════════════════════════════════════════════════

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
        await event.answer("⏭ Növbəti mahnıya keçildi")

    elif data.startswith("prev_"):
        chat_id = int(data.split("_")[1])
        await player.prev(chat_id)
        await event.answer("⏮ Yenidən başladılır / Keçilir")

    elif data.startswith("end_"):
        chat_id = int(data.split("_")[1])
        await player.end(chat_id)
        await event.answer("⏹ Dayandırıldı və Çatdan Çıxıldı")

    elif data.startswith("close_"):
        try:
            await event.delete()
        except Exception:
            pass
        await event.answer("❌ İdarəetmə paneli bağlandı")


# ═══════════════════════════════════════════════════════════════════
#  SISTEMİN BAŞLADILMASI
# ═══════════════════════════════════════════════════════════════════

async def start_userbot():
    global player
    
    # 1. Həm userbot, həm də köməkçi bot paralel olaraq start götürür
    await userbot.start()
    await tg_bot.start(bot_token=BOT_TOKEN)
    
    # 2. Player-i başladırıq və daxilinə köməkçi botun client-ını ötürürük
    player = RavenPlayer(userbot, bot_client=tg_bot)
    await player.start()
    
    logger.info("🎵 Raven Music Userbot (Səs Sistemi) uğurla işə düşdü!")
    logger.info("🤖 Köməkçi Bot (Düymə və Panel Sistemi) rəsmi olaraq aktivdir!")

    # FastApi/Uvicorn server sazlaması (Render-in sönməməsi üçün)
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    # Uvicorn serveri, userbotu və düymə botunu eyni anda asinxron işlədirik
    await asyncio.gather(
        server.serve(),
        userbot.run_until_disconnected(),
        tg_bot.run_until_disconnected()
    )


if __name__ == "__main__":
    asyncio.run(start_userbot())
