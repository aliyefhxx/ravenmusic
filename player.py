# player.py - Ses idarəetməsi (pytgcalls)
import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped, AudioImagePiped
from pytgcalls.types.input_stream import AudioParameters

from downloader import search_and_download, cleanup_files

logger = logging.getLogger(__name__)

# Hər chat üçün queue
queues: dict[int, list] = defaultdict(list)
# Cari oynanılan
now_playing: dict[int, dict] = {}
# Control mesajları (inline button olan)
control_messages: dict[int, Message] = {}
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


async def get_control_keyboard(chat_id: int, paused: bool = False) -> InlineKeyboardMarkup:
    play_pause = "⏸ Durdur" if not paused else "▶️ Davam"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏮ Geri", callback_data=f"prev_{chat_id}"),
            InlineKeyboardButton(play_pause, callback_data=f"pause_{chat_id}"),
            InlineKeyboardButton("⏭ İrəli", callback_data=f"skip_{chat_id}"),
        ],
        [
            InlineKeyboardButton("🔇 Bitir", callback_data=f"end_{chat_id}"),
            InlineKeyboardButton("❌ Bağla", callback_data=f"close_{chat_id}"),
        ]
    ])


async def send_now_playing(client: Client, chat_id: int, track: Track):
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
                await control_messages[chat_id].delete()
            except Exception:
                pass

        if track.thumbnail and os.path.exists(track.thumbnail):
            msg = await client.send_photo(
                chat_id,
                photo=track.thumbnail,
                caption=caption,
                reply_markup=keyboard
            )
        else:
            msg = await client.send_message(
                chat_id,
                caption,
                reply_markup=keyboard
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
    def __init__(self, client: Client):
        self.client = client
        self.calls = PyTgCalls(client)
        self._paused: dict[int, bool] = {}

    async def start(self):
        await self.calls.start()
        logger.info("PyTgCalls başladı")

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
                    await control_messages[chat_id].delete()
                    control_messages.pop(chat_id, None)
                except Exception:
                    pass
            return

        track: Track = queues[chat_id].pop(0)
        now_playing[chat_id] = track
        self._paused[chat_id] = False

        try:
            if track.thumbnail and os.path.exists(track.thumbnail):
                stream = AudioImagePiped(
                    track.file_path,
                    track.thumbnail,
                    audio_parameters=AudioParameters(bitrate=128)
                )
            else:
                stream = AudioPiped(
                    track.file_path,
                    audio_parameters=AudioParameters(bitrate=128)
                )

            # Aktiv call varsa change_stream, yoxdursa join
            try:
                await self.calls.change_stream(chat_id, stream)
            except Exception:
                await self.calls.join_group_call(
                    chat_id,
                    stream,
                    stream_type=None
                )

            await send_now_playing(self.client, chat_id, track)

        except Exception as e:
            logger.error(f"Oynatma xətası: {e}")
            await self.play_next(chat_id)

    async def add_to_queue(
        self,
        client: Client,
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

            # Əgər hal-hazırda heç nə oxunmursa, başlat
            if chat_id not in now_playing or not now_playing.get(chat_id):
                await self.play_next(chat_id)

            return True
        finally:
            active_searches[chat_id] -= 1

    async def skip(self, chat_id: int):
        """Növbəti mahnıya keç"""
        track = now_playing.get(chat_id)
        if track:
            cleanup_files(track.request_id)
        await self.play_next(chat_id)

    async def end(self, chat_id: int):
        """Oxumağı tamamilə dayandır"""
        track = now_playing.get(chat_id)
        if track:
            cleanup_files(track.request_id)

        # Queue-dakı bütün faylları sil
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
                await control_messages[chat_id].delete()
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
        """Əvvəlki mahnıya qayıt (bu versiyada skip kimi işləyir)"""
        await self.skip(chat_id)
