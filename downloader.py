# downloader.py - @SongFastBot vasitəsilə mahnı yüklənməsi (Telethon v1 əsaslı)
import asyncio
import os
import logging
from telethon import TelegramClient

logger = logging.getLogger(__name__)

SONG_BOT = "SongFastBot"
DOWNLOAD_DIR = "downloads"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def search_and_download(client: TelegramClient, song_name: str, request_id: str) -> dict | None:
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
        await asyncio.sleep(3)  # Botun axtarış etməsi üçün 3 saniyə gözləyirik

        # 3. Bot-dan cavab gəl (inline keyboard olan mesajı tapırıq)
        search_response = None
        async for msg in client.iter_messages(SONG_BOT, limit=5):
            if msg.buttons:
                search_response = msg
                break

        if not search_response:
            logger.warning(f"SongFastBot cavab vermədi və ya buton tapılmadı: {song_name}")
            return None

        # 4. İlk inline buttona bas (birinci nəticə)
        # Telethon-da buton matrisi msg.buttons daxilində saxlanılır
        try:
            first_button = search_response.buttons[0][0]
            # Botun daxili callback datasını tetikləyirik
            await first_button.click()
            logger.info(f"SongFastBot-da 1-ci düyməyə basıldı: {first_button.text}")
        except Exception as btn_err:
            logger.error(f"Butona klikləmək mümkün olmadı: {btn_err}")
            return None

        # Botun faylı hazırlayıb göndərməsi üçün gözləmə müddəti
        await asyncio.sleep(5)

        # 5. Gələn audio faylı tap (Son 10 mesajı yoxlayırıq)
        audio_msg = None
        async for msg in client.iter_messages(SONG_BOT, limit=10):
            if msg.audio or msg.voice or msg.document:
                audio_msg = msg
                break

        if not audio_msg:
            logger.warning(f"Audio fayl gəlmədi: {song_name}")
            return None

        # 6. Fayl məlumatlarını çıxar
        if audio_msg.audio:
            # Telethon-da audio atributları attributes daxilində saxlanılır
            for attr in audio_msg.audio.attributes:
                if hasattr(attr, 'title') and attr.title:
                    result["title"] = attr.title
                if hasattr(attr, 'duration') and attr.duration:
                    result["duration"] = attr.duration

            # Əgər mahnının şəkli (thumbnail) varsa yükləyirik
            if audio_msg.photo:
                thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{request_id}.jpg")
                await client.download_media(audio_msg.photo, file=thumb_path)
                result["thumbnail"] = thumb_path

        # 7. Audio faylı yüklə
        file_path = os.path.join(DOWNLOAD_DIR, f"audio_{request_id}.mp3")
        # Telethon-un birbaşa mesaj obyektindən media endirmə metodu
        await client.download_media(audio_msg, file=file_path)
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
