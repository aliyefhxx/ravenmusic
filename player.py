# player.py - Ses idarəetməsi (Telethon + pytgcalls v2)
import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from telethon import TelegramClient, Button
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality, VideoQuality

from downloader import search_and_download, cleanup_files

logger = logging.getLogger(__name__)

# Hər chat üçün queue
queues: dict[int, list] = defaultdict(list)
# Cari oynanılan
now_playing: dict[int, dict] = {}
# Control mesajları
control_messages: dict[int, any] = {}
# Aktiv axtarış sayı (max 10)
active_searches: dict[int, int] = defaultdict(int)

MAX_QUEUE = 10


@dataclass
class Track:
    song_name: str
    file_path: str
    title: str
    thumbnail: Optional[str]
    duration: Optional[int]
    request_id: str
    requested_by: str = ""


async def get_control_keyboard(chat_id: int, paused: bool = False):
    play_pause = "⏸ Durdur" if not paused else "▶️ Davam"
    return [
        [
            Button.inline("⏮ Geri", data=f"prev_{chat_id}"),
            Button.inline(play_pause, data=f"pause_{chat_id}"),
            Button.inline("⏭ İrəli", data=f"skip_{chat_id}"),
        ],
        [
            Button.inline("🔇 Bitir", data=f"end_{chat_id}"),
            Button.inline("❌ Bağla", data=f"close_{chat_id}"),
        ]
    ]


async def send_now_playing(client: TelegramClient, chat_id: int, track: Track):
    """İnline buttonlarla 'İndi oxunur' mesajı göndər"""
    keyboard = await get_control_keyboard(chat_id)
    caption = (
        f"🎵 **İndi Oxunur**\n\n"
        f"🎼 **{track.title}**\n"
        f"⏱ Müddət: {format_duration(track.duration)}\n"
        f"👤 Tələb edən: {track.requested_by}"
    )

    try:
        # Köhnə control mesajını sil
        if chat_id in control_messages:
            try:
                await client.delete_messages(chat_id, control_messages[chat_id].id)
            except Exception:
                pass

        if track.thumbnail and os.path.exists(track.thumbnail):
            msg = await client.send_file(
                chat_id,
                file=track.thumbnail,
                caption=caption,
                buttons=keyboard
            )
        else:
            msg = await client.send_message(
                chat_id,
                message=caption,
                buttons=keyboard
            )
        control_messages[chat_id] = msg
    except Exception as e:
        logger.error(f"Control mesajı göndərilmədi: {e}")


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class RavenPlayer:
    def __init__(self, client: TelegramClient):
        self.client = client
        self.calls = PyTgCalls(client)
        self._paused: dict[int, bool] = {}

        # Telethon-un daxili "UpdateGroupCall" çatışmazlıq xətasını (chat_id xətası)
        # arxa planda süzgəcdən keçirmək üçün raw yeniləmə funksiyasını manipulyasiya edirik.
        orig_dispatch = self.client._dispatch_update
        async def safe_dispatch(update, others):
            if type(update).__name__ == 'UpdateGroupCall' and not hasattr(update, 'chat_id'):
                return
            try:
                await orig_dispatch(update, others)
            except Exception:
                pass
        self.client._dispatch_update = safe_dispatch

    async def start(self):
        await self.calls.start()
        logger.info("PyTgCalls (Telethon ilə) başladı")

    async def play_next(self, chat_id: int):
        """Queue-dan növbəti mahnını oxut"""
        if not queues[chat_id]:
            now_playing.pop(chat_id, None)
            self._paused.pop(chat_id, None)
            try:
                await self.calls.leave_group_call(chat_id)
            except Exception:
                pass
            if chat_id in control_messages:
                try:
                    await self.client.delete_messages(chat_id, control_messages[chat_id].id)
                    control_messages.pop(chat_id, None)
                except Exception:
                    pass
            return

        track: Track = queues[chat_id].pop(0)
        now_playing[chat_id] = track
        self._paused[chat_id] = False

        try:
            # NO_VIDEO flag-i yerinə, AudioQuality və VideoQuality parametrlərini təyin edirik.
            # Əgər video yoxdursa, video parametrini boş buraxırıq ki, NO_VIDEO xətası verməsin.
            if track.thumbnail and os.path.exists(track.thumbnail):
                stream = MediaStream(
                    track.file_path,
                    audio_parameters=AudioQuality.HIGH,
                    video_parameters=VideoQuality.THUMBNAIL
                )
            else:
                stream = MediaStream(
                    track.file_path,
                    audio_parameters=AudioQuality.HIGH
                )

            try:
                await self.calls.change_stream(chat_id, stream)
            except Exception:
                await self.calls.join_group_call(
                    chat_id,
                    stream
                )

            await send_now_playing(self.client, chat_id, track)

        except Exception as e:
            logger.error(f"Oynatma xətası: {e}")
            await self.play_next(chat_id)

    async def add_to_queue(
        self,
        client,
        chat_id: int,
        song_name: str,
        request_id: str,
        requested_by: str = ""
    ) -> bool:
        """Mahnı yüklə və queue-ya əlavə et"""
        if active_searches[chat_id] >= MAX_QUEUE:
            return False

        active_searches[chat_id] += 1
        try:
            result = await search_and_download(client, song_name, request_id)
            if not result or not result["file_path"]:
                return False

            track = Track(
                song_name=song_name,
                file_path=result["file_path"],
                title=result["title"],
                thumbnail=result["thumbnail"],
                duration=result["duration"],
                request_id=request_id,
                requested_by=requested_by
            )

            queues[chat_id].append(track)

            if chat_id not in now_playing or not now_playing.get(chat_id):
                await self.play_next(chat_id)

            return True
        finally:
            active_searches[chat_id] -= 1

    async def skip(self, chat_id: int):
        track = now_playing.get(chat_id)
        if track:
            cleanup_files(track.request_id)
        await self.play_next(chat_id)

    async def end(self, chat_id: int):
        track = now_playing.get(chat_id)
        if track:
            cleanup_files(track.request_id)

        for t in queues.get(chat_id, []):
            cleanup_files(t.request_id)
        queues[chat_id].clear()
        now_playing.pop(chat_id, None)
        self._paused.pop(chat_id, None)

        try:
            await self.calls.leave_group_call(chat_id)
        except Exception:
            pass

        if chat_id in control_messages:
            try:
                await self.client.delete_messages(chat_id, control_messages[chat_id].id)
                control_messages.pop(chat_id, None)
            except Exception:
                pass

    async def pause(self, chat_id: int):
        if self._paused.get(chat_id):
            await self.calls.resume_stream(chat_id)
            self._paused[chat_id] = False
        else:
            await self.calls.pause_stream(chat_id)
            self._paused[chat_id] = True
        return self._paused[chat_id]

    def is_paused(self, chat_id: int) -> bool:
        return self._paused.get(chat_id, False)

    async def prev(self, chat_id: int):
        await self.skip(chat_id)
