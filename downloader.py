# downloader.py - @SongFastBot vasitəsilə mahnı yüklənməsi
import asyncio
import os
import logging
from pyrogram import Client
from pyrogram.types import Message

logger = logging.getLogger(__name__)

SONG_BOT = "SongFastBot"
DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def search_and_download(client: Client, song_name: str, request_id: str) -> dict | None:
    """
    @SongFastBot-a /start göndərir, mahnı axtarır, ilk nəticəni seçir,
    faylı yükləyir. Uğurlu olsa dict qaytarır, olmasa None.
    """
    result = {
        "file_path": None,
        "title": song_name,
        "thumbnail": None,
        "duration": None,
    }

    try:
        # 1. /start göndər
        await client.send_message(SONG_BOT, "/start")
        await asyncio.sleep(2)

        # 2. Mahnı adını göndər
        await client.send_message(SONG_BOT, song_name)
        await asyncio.sleep(2)

        # 3. Bot-dan cavab gəl (inline keyboard ilə)
        search_response: Message | None = None
        async for msg in client.get_chat_history(SONG_BOT, limit=5):
            if msg.reply_markup and hasattr(msg.reply_markup, "inline_keyboard"):
                search_response = msg
                break

        if not search_response:
            logger.warning(f"SongFastBot cavab vermədi: {song_name}")
            return None

        # 4. İlk inline buttona bas (birinci nəticə)
        keyboard = search_response.reply_markup.inline_keyboard
        if not keyboard or not keyboard[0]:
            return None

        first_button = keyboard[0][0]
        await search_response.click(first_button.callback_data)
        await asyncio.sleep(5)

        # 5. Gələn audio faylı tap
        audio_msg: Message | None = None
        async for msg in client.get_chat_history(SONG_BOT, limit=10):
            if msg.audio or msg.voice or msg.document:
                audio_msg = msg
                break

        if not audio_msg:
            logger.warning(f"Audio fayl gəlmədi: {song_name}")
            return None

        # 6. Fayl məlumatlarını çıxar
        media = audio_msg.audio or audio_msg.voice or audio_msg.document
        if audio_msg.audio:
            result["title"] = audio_msg.audio.title or song_name
            result["duration"] = audio_msg.audio.duration
            if audio_msg.audio.thumbs:
                thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{request_id}.jpg")
                await client.download_media(
                    audio_msg.audio.thumbs[0].file_id,
                    file_name=thumb_path
                )
                result["thumbnail"] = thumb_path

        # 7. Audio faylı yüklə
        file_path = os.path.join(DOWNLOAD_DIR, f"audio_{request_id}.mp3")
        await client.download_media(audio_msg, file_name=file_path)
        result["file_path"] = file_path

        logger.info(f"Mahnı yükləndi: {result['title']} -> {file_path}")
        return result

    except Exception as e:
        logger.error(f"Yükləmə xətası ({song_name}): {e}")
        return None


def cleanup_files(request_id: str):
    """Müvəqqəti faylları sil"""
    for prefix in ["audio_", "thumb_"]:
        path = os.path.join(DOWNLOAD_DIR, f"{prefix}{request_id}.mp3")
        if os.path.exists(path):
            os.remove(path)
        path_jpg = os.path.join(DOWNLOAD_DIR, f"{prefix}{request_id}.jpg")
        if os.path.exists(path_jpg):
            os.remove(path_jpg)
