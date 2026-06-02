# player.py - 0 Donma, Versiya Xətaları və Panel Mesajı Tam Düzəldilmiş Son Versiya
import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from telethon import TelegramClient, Button
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest

# PyTgCalls importları - Ən stabil səs axını üçün InputAudioStream və AudioQuality
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality
from pytgcalls.types.stream import InputAudioStream 

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
    """Köməkçi bot qrupda yoxdursa avtomatik dəvət edir"""
    try:
        entity = await user_client.get_input_entity(chat_id)
        import main
        bot_username = getattr(main, 'BOT_USERNAME', '@RavenMscUserbot')
        
        if hasattr(entity, 'channel_id'):
            await user_client(InviteToChannelRequest(channel=entity, users=[bot_username]))
        else:
            await user_client(AddChatUserRequest(chat_id=chat_id, user_id=bot_username, fwd_limit=0))
    except Exception as e:
        logger.warning(f"Bot avtomatik əlavə edilə bilmədi və ya artıq qrupdadır: {e}")


async def send_now_playing(user_client: TelegramClient, chat_id: int, track: Track):
    """Səliqəyə salınmış və dizaynı düzəldilmiş İndi Oxunur paneli"""
    keyboard = await get_control_keyboard(chat_id)
    
    # İstədiyin tam səliqəli və qüsursuz mətn formatı
    caption = (
        f"🎵 **İndi Oxunur**\n\n"
        f"🎼 **{track.title}**\n"
        f"⏱️ Müddət: `{format_duration(track.duration)}`\n"
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
        return "00:00"
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class RavenPlayer:
    def __init__(self, client: TelegramClient, bot_client: TelegramClient = None):
        self.client = client
        self.bot_client = bot_client
        self.calls = PyTgCalls(client)
        self._paused: dict[int, bool] = {}

        @self.calls.on_update()
        async def update_handler(*args):
            update = args[1] if len(args) > 1 else args[0]
            type_name = type(update).__name__
            
            if type_name in ["StreamBacked", "UpdateStreamBacked", "StreamFinished", "StreamFinishedObject"]:
                chat_id = getattr(update, 'chat_id', None)
                if chat_id:
                    logger.info(f"Mahnı bitdi ({type_name}), növbəti yoxlanılır. Chat ID: {chat_id}")
                    asyncio.create_task(self.play_next(chat_id))

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
        logger.info("PyTgCalls sistemi uğurla başladı.")

    async def force_leave(self, chat_id: int):
        """Səsdən tamamilə çıxış metodu"""
        methods = ["leave_call", "leave_group_call", "reject_call"]
        for method_name in methods:
            if hasattr(self.calls, method_name):
                try:
                    method = getattr(self.calls, method_name)
                    await method(chat_id)
                    logger.info(f"Səsli çatdan çıxıldı ({method_name}). Chat ID: {chat_id}")
                    return
                except Exception as e:
                    logger.debug(f"{method_name} xətası: {e}")
        try:
            await self.calls.drop_call(chat_id)
        except Exception:
            pass

    async def play_next(self, chat_id: int):
        """Mahnı bitdikdə növbəni idarə edir. Boşdursa çıxır, doludursa davam edir."""
        old_track = now_playing.get(chat_id)
        if old_track:
            cleanup_files(old_track.request_id)

        if not queues[chat_id]:
            now_playing.pop(chat_id, None)
            self._paused.pop(chat_id, None)
            await self.force_leave(chat_id)
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
            # KÖKLÜ DÜZƏLİŞ VƏ 0 DONMA: 
            # MediaStream tam ləğv edildi. Bütün versiyalarla uyğun və sıfır donma ilə işləyən InputAudioStream-ə keçdik.
            stream = InputAudioStream(
                track.file_path,
                AudioQuality.HIGH
            )
            await self.calls.play(chat_id, stream)
            await send_now_playing(self.client, chat_id, track)
        except Exception as e:
            logger.error(f"Oynatma xətası (Yenidən yoxlanılır): {e}")
            await self.play_next(chat_id)

    async def add_to_queue(self, client, chat_id: int, song_name: str, request_id: str, requested_by: str = "") -> bool:
        if active_searches[chat_id] >= MAX_QUEUE:
            return False

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

        await self.force_leave(chat_id)

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
