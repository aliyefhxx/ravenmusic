# player.py - Tam Versiya-Müstəqil (Universal) Versiya
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
# Moduldan import etmək yerinə birbaşa PyTgCalls metodlarını istifadə edirik
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

# [Digər köməkçi funksiyalar (get_control_keyboard, check_and_invite_bot, send_now_playing, format_duration) əvvəlki kimi qalır]

async def get_control_keyboard(chat_id: int, paused: bool = False):
    play_pause = "⏸ Durdur" if not paused else "▶️ Davam"
    return [[Button.inline("⏮ Geri", data=f"prev_{chat_id}"), Button.inline(play_pause, data=f"pause_{chat_id}"), Button.inline("⏭ İrəli", data=f"skip_{chat_id}")], [Button.inline("🔇 Bitir", data=f"end_{chat_id}"), Button.inline("❌ Bağla", data=f"close_{chat_id}")]]

async def check_and_invite_bot(user_client: TelegramClient, chat_id: int):
    try:
        entity = await user_client.get_input_entity(chat_id)
        import main
        bot_username = getattr(main, 'BOT_USERNAME', '@RavenMscUserbot')
        if hasattr(entity, 'channel_id'): await user_client(InviteToChannelRequest(channel=entity, users=[bot_username]))
        else: await user_client(AddChatUserRequest(chat_id=chat_id, user_id=bot_username, fwd_limit=0))
    except: pass

async def send_now_playing(user_client: TelegramClient, chat_id: int, track: Track):
    keyboard = await get_control_keyboard(chat_id)
    caption = f"🎵 **İndi Oxunur**\n\n🎼 **{track.title}**\n⏱️ Müddət: `{format_duration(track.duration)}`\n👤 Tələb edən: {track.requested_by}\n\nℹ️ _Düymələr işləmirsə, .end və ya .skip komandalarından istifadə edin._"
    try:
        if chat_id in control_messages:
            try: await user_client.delete_messages(chat_id, control_messages[chat_id].id)
            except: pass
        if track.thumbnail and os.path.exists(track.thumbnail): msg = await user_client.send_file(chat_id, file=track.thumbnail, caption=caption, buttons=keyboard)
        else: msg = await user_client.send_message(chat_id, message=caption, buttons=keyboard)
        control_messages[chat_id] = msg
    except: pass

def format_duration(seconds: Optional[int]) -> str:
    if not seconds: return "00:00"
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

class RavenPlayer:
    def __init__(self, client: TelegramClient, bot_client: TelegramClient = None):
        self.client = client
        self.calls = PyTgCalls(client)
        self._paused: dict[int, bool] = {}

    async def start(self):
        await self.calls.start()

    async def force_leave(self, chat_id: int):
        for method in ["leave_call", "leave_group_call", "reject_call", "drop_call"]:
            if hasattr(self.calls, method):
                try: await getattr(self.calls, method)(chat_id)
                except: continue
                break

    async def play_next(self, chat_id: int):
        old_track = now_playing.get(chat_id)
        if old_track: cleanup_files(old_track.request_id)

        if not queues[chat_id]:
            now_playing.pop(chat_id, None)
            await self.force_leave(chat_id)
            return

        track: Track = queues[chat_id].pop(0)
        now_playing[chat_id] = track
        
        try:
            # UNIVERSAL OYNATMA: Modul import etmədən birbaşa fayl yolunu ötürürük
            # Bu, bütün PyTgCalls versiyalarında çalışan ən stabil üsuldur
            await self.calls.join_group_call(chat_id, track.file_path)
            await send_now_playing(self.client, chat_id, track)
        except Exception as e:
            logger.error(f"Oynatma xətası: {e}")
            await self.play_next(chat_id)

    async def add_to_queue(self, client, chat_id: int, song_name: str, request_id: str, requested_by: str = "") -> bool:
        await check_and_invite_bot(self.client, chat_id)
        result = await search_and_download(client, song_name, request_id)
        if not result or not result["file_path"]: return False
        track = Track(song_name, result["file_path"], result["title"], result["thumbnail"], result["duration"], request_id, requested_by)
        queues[chat_id].append(track)
        if chat_id not in now_playing: await self.play_next(chat_id)
        return True

    async def skip(self, chat_id: int): await self.play_next(chat_id)
    
    async def end(self, chat_id: int):
        queues[chat_id].clear()
        await self.force_leave(chat_id)
