# player.py - Tam Avtomatlaşdırılmış Səs Sistemi (0 Donma, Avto-Çıxış və Yedək Komanda Dəstəyi)
import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from telethon import TelegramClient, Button
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream

from downloader import search_and_download, cleanup_files

logger = logging.getLogger(__name__)

queues: dict[int, list] = defaultdict(list)
now_playing: dict[int, dict] = {}
control_messages: dict[int, any] = {}
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


async def check_and_invite_bot(user_client: TelegramClient, chat_id: int):
    """Əgər köməkçi bot qrupda yoxdursa, userbot onu avtomatik qrupa dəvət edir"""
    try:
        # Chat obyektinin tipini yoxlayırıq (Normal qrup yoxsa Superqrup/Kanal)
        entity = await user_client.get_input_entity(chat_id)
        from main import BOT_USERNAME
        
        logger.info(f"Köməkçi bot ({BOT_USERNAME}) {chat_id} qrupuna avtomatik əlavə edilir...")
        if hasattr(entity, 'channel_id'):
            await user_client(InviteToChannelRequest(channel=entity, users=[BOT_USERNAME]))
        else:
            await user_client(AddChatUserRequest(chat_id=chat_id, user_id=BOT_USERNAME, fwd_limit=0))
    except Exception as e:
        logger.warning(f"Bot avtomatik əlavə edilə bilmədi (İcazə yoxdur və ya bot artıq qrupdadır): {e}")


async def send_now_playing(user_client: TelegramClient, chat_id: int, track: Track):
    """Nəzarət panelini ekrana çıxarır"""
    keyboard = await get_control_keyboard(chat_id)
    caption = (
        f"🎵 **İndi Oxunur**\n\n"
        f"🎼 **{track.title}**\n"
        f"⏱ Müddət: {format_duration(track.duration)}\n"
        f"👤 Tələb edən: {track.requested_by}\n\n"
        f"ℹ️ _Düymələr işləmirsə, `.end` və ya `.skip` komandalarından istifadə edin._"
    )

    try:
        if chat_id in control_messages:
            try:
                await user_client.delete_messages(chat_id, control_messages[chat_id].id)
            except Exception:
                pass

        if track.thumbnail and os.path.exists(track.thumbnail):
            msg = await user_client.send_file(chat_id, file=track.thumbnail, caption=caption, buttons=keyboard)
        else:
            msg = await user_client.send_message(chat_id, message=caption, buttons=keyboard)
        control_messages[chat_id] = msg
    except Exception as e:
        logger.error(f"Panel göndərilərkən xəta: {e}")


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class RavenPlayer:
    def __init__(self, client: TelegramClient, bot_client: TelegramClient = None):
        self.client = client
        self.bot_client = bot_client
        self.calls = PyTgCalls(client)
        self._paused: dict[int, bool] = {}

        # PyTgCalls v2 üçün avtomatik növbəti mahnıya keçid hadisəsi (Event Handler)
        @self.calls.on_stream_end()
        async def stream_end_handler(chat_id: int, stream):
            logger.info(f"Mahnı bitdi, növbəti yoxlanılır. Chat ID: {chat_id}")
            # Asinxron dövr daxilində növbəti mahnını tetikləyirik
            asyncio.create_task(self.play_next(chat_id))

        # Telethon yeniləmə filtri
        orig_dispatch = self.client._dispatch_update
        async def safe_dispatch(update, others=None):
            if type(update).__name__ == 'UpdateGroupCall' and not hasattr(update, 'chat_id'):
                return
            try:
                if others is not None:
                    await orig_dispatch(update, others)
                else:
                    await orig_dispatch(update)
            except Exception:
                pass
        self.client._dispatch_update = safe_dispatch

    async def start(self):
        await self.calls.start()
        logger.info("PyTgCalls sistemi başladı.")

    async def play_next(self, chat_id: int):
        """Mahnı bitdikdə növbəni yoxlayır, yoxdursa səsdən tamamilə çıxır!"""
        # Cari ifa olunan faylı təmizləyirik
        old_track = now_playing.get(chat_id)
        if old_track:
            cleanup_files(old_track.request_id)

        # Əgər növbədə ard-arda mahnı YOXDURSA, səsdən çıx!
        if not queues[chat_id]:
            now_playing.pop(chat_id, None)
            self._paused.pop(chat_id, None)
            try:
                # Səsli çatdan tamamilə çıxış (Avtomatik çıxış rejimi)
                await self.calls.reject_call(chat_id)
                logger.info(f"Növbə boşdur, səsli çatdan avtomatik çıxıldı. Chat ID: {chat_id}")
            except Exception:
                pass
            if chat_id in control_messages:
                try:
                    await self.client.delete_messages(chat_id, control_messages[chat_id].id)
                    control_messages.pop(chat_id, None)
                except Exception:
                    pass
            return

        # Əgər növbədə mahnı VARSA (2-6 fərq etmir), davam et!
        track: Track = queues[chat_id].pop(0)
        now_playing[chat_id] = track
        self._paused[chat_id] = False

        try:
            # DONMASIZ AXIN: Video ləğv edildi, bitreyt tam optimallaşdırıldı
            stream = MediaStream(
                track.file_path,
                audio_parameters=AudioQuality.MEDIUM,
                video_parameters=None
            )

            await self.calls.play(chat_id, stream)
            await send_now_playing(self.client, chat_id, track)

        except Exception as e:
            logger.error(f"Oynatma xətası: {e}")
            await self.play_next(chat_id)

    async def add_to_queue(self, client, chat_id: int, song_name: str, request_id: str, requested_by: str = "") -> bool:
        """Mahnını növbəyə salır"""
        if active_searches[chat_id] >= MAX_QUEUE:
            return False

        # İlk öncə botun qrupda olub-olmadığını yoxlayıb, yoxdursa əlavə edirik
        await check_and_invite_bot(self.client, chat_id)

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
            await self.calls.reject_call(chat_id)
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
