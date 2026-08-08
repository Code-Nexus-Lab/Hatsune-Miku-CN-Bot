"""Asynchronous voice music playback using yt-dlp and FFmpeg."""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
import yt_dlp
from discord.ext import commands

from utils.embeds import base_embed, error_embed, success_embed

if TYPE_CHECKING:
    from bot import HatsuneMikuBot


LOGGER = logging.getLogger(__name__)
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "default_search": "ytsearch",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
}
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


@dataclass(slots=True)
class Track:
    """Resolved media metadata."""

    title: str
    webpage_url: str
    stream_url: str
    requester_id: int
    duration: int | None


@dataclass
class Player:
    """Mutable per-guild playback state."""

    guild_id: int
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    volume: float = 0.5
    loop: bool = False
    autoplay: bool = False
    task: asyncio.Task[None] | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    skip_requested: bool = False


class Music(commands.Cog):
    """Play web audio in Discord voice channels."""

    def __init__(self, bot: HatsuneMikuBot) -> None:
        self.bot = bot
        self.players: dict[int, Player] = {}

    def cog_unload(self) -> None:
        """Cancel background players on extension unload."""
        for player in self.players.values():
            if player.task:
                player.task.cancel()

    def _player(self, guild_id: int) -> Player:
        player = self.players.get(guild_id)
        if player is None:
            player = Player(guild_id)
            self.players[guild_id] = player
        return player

    @commands.command()
    @commands.guild_only()
    async def join(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Join the caller's voice channel."""
        channel = self._author_voice_channel(ctx)
        if channel is None:
            return
        voice = ctx.guild.voice_client
        if voice and voice.channel != channel:
            await voice.move_to(channel)
        elif voice is None:
            await channel.connect(reconnect=True, timeout=20)
        await ctx.send(embed=success_embed("🎶 Connected", f"Joined {channel.mention}."))

    @commands.command()
    @commands.guild_only()
    async def leave(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Disconnect and clear this server's in-memory playback state."""
        if not await self._in_bot_channel(ctx):
            return
        voice = ctx.guild.voice_client
        if voice:
            await voice.disconnect(force=True)
        self._remove_player(ctx.guild.id)
        await ctx.send(embed=success_embed("👋 Disconnected", "Playback queue cleared."))

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def play(self, ctx: commands.Context[HatsuneMikuBot], *, query: str) -> None:
        """Search for or queue a track URL."""
        if len(query) > 300:
            await ctx.send(embed=error_embed("Keep the search or URL under 300 characters."))
            return
        channel = self._author_voice_channel(ctx)
        if channel is None:
            return
        voice = ctx.guild.voice_client
        if voice is None:
            voice = await channel.connect(reconnect=True, timeout=20)
        elif voice.channel != channel:
            await voice.move_to(channel)
        async with ctx.typing():
            track = await self._extract(query, ctx.author.id)
        if track is None:
            await ctx.send(embed=error_embed("I couldn't find playable audio for that query."))
            return
        player = self._player(ctx.guild.id)
        player.queue.append(track)
        self._persist_queue(player)
        if player.task is None or player.task.done():
            player.task = asyncio.create_task(self._run_player(ctx.guild, player))
        player.wake.set()
        await ctx.send(embed=success_embed("➕ Queued", f"**{track.title}**"))

    @commands.command()
    @commands.guild_only()
    async def pause(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Pause active audio."""
        if not await self._in_bot_channel(ctx):
            return
        voice = ctx.guild.voice_client
        if voice and voice.is_playing():
            voice.pause()
            await ctx.send(embed=success_embed("⏸️ Paused", "Playback paused."))

    @commands.command()
    @commands.guild_only()
    async def resume(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Resume paused audio."""
        if not await self._in_bot_channel(ctx):
            return
        voice = ctx.guild.voice_client
        if voice and voice.is_paused():
            voice.resume()
            await ctx.send(embed=success_embed("▶️ Resumed", "Playback resumed."))

    @commands.command()
    @commands.guild_only()
    async def skip(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Skip the current track."""
        if not await self._in_bot_channel(ctx):
            return
        voice = ctx.guild.voice_client
        if voice and (voice.is_playing() or voice.is_paused()):
            self._player(ctx.guild.id).skip_requested = True
            voice.stop()
            await ctx.send(embed=success_embed("⏭️ Skipped", "Skipping current track."))

    @commands.command(name="queue")
    @commands.guild_only()
    async def queue_command(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Display the current track queue."""
        player = self._player(ctx.guild.id)
        lines = [f"**Now:** {player.current.title}"] if player.current else []
        lines.extend(f"**{i}.** {track.title}" for i, track in enumerate(player.queue, 1))
        await ctx.send(embed=base_embed("🎵 Music Queue", "\n".join(lines) or "The queue is empty."))

    @commands.command()
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Show the current track."""
        track = self._player(ctx.guild.id).current
        await ctx.send(embed=base_embed("🎧 Now Playing", f"**{track.title}**" if track else "Nothing is playing."))

    @commands.command()
    @commands.guild_only()
    async def volume(self, ctx: commands.Context[HatsuneMikuBot], percent: commands.Range[int, 0, 100]) -> None:
        """Set playback volume."""
        if not await self._in_bot_channel(ctx):
            return
        player = self._player(ctx.guild.id)
        player.volume = percent / 100
        voice = ctx.guild.voice_client
        if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = player.volume
        await ctx.send(embed=success_embed("🔊 Volume", f"Set to **{percent}%**."))

    @commands.command()
    @commands.guild_only()
    async def stop(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Stop playback and clear queued tracks."""
        if not await self._in_bot_channel(ctx):
            return
        player = self._player(ctx.guild.id)
        player.queue.clear()
        player.loop = False
        self._persist_queue(player)
        voice = ctx.guild.voice_client
        if voice:
            voice.stop()
        await ctx.send(embed=success_embed("⏹️ Stopped", "Queue cleared."))

    @commands.command()
    @commands.guild_only()
    async def shuffle(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Shuffle queued tracks."""
        if not await self._in_bot_channel(ctx):
            return
        player = self._player(ctx.guild.id)
        random.shuffle(player.queue)
        self._persist_queue(player)
        await ctx.send(embed=success_embed("🔀 Shuffled", "The upcoming queue was shuffled."))

    @commands.command()
    @commands.guild_only()
    async def loop(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Toggle repeating the current track."""
        if not await self._in_bot_channel(ctx):
            return
        player = self._player(ctx.guild.id)
        player.loop = not player.loop
        await ctx.send(embed=success_embed("🔁 Loop", f"Loop is **{'on' if player.loop else 'off'}**."))

    @commands.command()
    @commands.guild_only()
    async def autoplay(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Toggle automatic related-track search when the queue finishes."""
        if not await self._in_bot_channel(ctx):
            return
        player = self._player(ctx.guild.id)
        player.autoplay = not player.autoplay
        await ctx.send(
            embed=success_embed(
                "♾️ Autoplay",
                f"Autoplay is **{'on' if player.autoplay else 'off'}**.",
            )
        )

    async def _run_player(self, guild: discord.Guild, player: Player) -> None:
        """Play queued audio sequentially until the queue is empty."""
        try:
            while True:
                if player.current is None or player.skip_requested or not player.loop:
                    player.skip_requested = False
                    if not player.queue:
                        if not player.autoplay or player.current is None:
                            return
                        generated = await self._extract(
                            f"ytsearch1:{player.current.title} mix",
                            0,
                        )
                        if generated is None:
                            return
                        player.queue.append(generated)
                    player.current = player.queue.popleft()
                    self._persist_queue(player)
                voice = guild.voice_client
                if voice is None or not voice.is_connected():
                    return
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(
                        player.current.stream_url,
                        before_options=FFMPEG_BEFORE_OPTIONS,
                        options="-vn",
                    ),
                    volume=player.volume,
                )
                finished = asyncio.Event()
                voice.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(finished.set))
                await finished.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Music player failed for guild %s.", guild.id)
        finally:
            player.current = None
            player.task = None

    async def _extract(self, query: str, requester_id: int) -> Track | None:
        """Resolve a media search or URL without blocking Discord's event loop."""
        def extract() -> dict[str, object]:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                return ytdl.extract_info(query, download=False)
        try:
            info = await asyncio.to_thread(extract)
            if "entries" in info:
                info = next(entry for entry in info["entries"] if entry)
            return Track(str(info["title"]), str(info["webpage_url"]), str(info["url"]), requester_id, info.get("duration"))
        except (yt_dlp.utils.DownloadError, KeyError, StopIteration):
            LOGGER.info("yt-dlp could not resolve query: %s", query)
            return None

    def _persist_queue(self, player: Player) -> None:
        """Persist queued metadata without delaying voice playback."""
        async def save() -> None:
            await self.bot.database.execute("DELETE FROM music_queue WHERE guild_id = ?", (player.guild_id,))
            for position, track in enumerate(player.queue):
                await self.bot.database.execute(
                    "INSERT INTO music_queue (guild_id, position, title, webpage_url, requested_by, duration_seconds) VALUES (?, ?, ?, ?, ?, ?)",
                    (player.guild_id, position, track.title, track.webpage_url, track.requester_id, track.duration),
                )
        asyncio.create_task(save())

    async def _in_bot_channel(self, ctx: commands.Context[HatsuneMikuBot]) -> bool:
        voice = ctx.guild.voice_client
        channel = self._author_voice_channel(ctx, send_error=False)
        if voice is None or channel is None or voice.channel != channel:
            await ctx.send(embed=error_embed("Join my voice channel to control playback."))
            return False
        return True

    def _author_voice_channel(self, ctx: commands.Context[HatsuneMikuBot], send_error: bool = True) -> discord.VoiceChannel | None:
        channel = ctx.author.voice.channel if ctx.author.voice else None
        if not isinstance(channel, discord.VoiceChannel):
            if send_error:
                asyncio.create_task(ctx.send(embed=error_embed("Join a voice channel first.")))
            return None
        return channel

    def _remove_player(self, guild_id: int) -> None:
        player = self.players.pop(guild_id, None)
        if player and player.task:
            player.task.cancel()


async def setup(bot: HatsuneMikuBot) -> None:
    """Load the cog."""
    await bot.add_cog(Music(bot))
