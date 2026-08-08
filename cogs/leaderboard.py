"""Automatically maintained leaderboard-channel display."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from utils.embeds import base_embed, success_embed

if TYPE_CHECKING:
    from bot import HatsuneMikuBot


class LeaderboardDisplay(commands.Cog):
    """Maintain one leaderboard embed in each configured guild channel."""

    def __init__(self, bot: HatsuneMikuBot) -> None:
        self.bot = bot
        self.refresh_leaderboards.start()

    def cog_unload(self) -> None:
        self.refresh_leaderboards.cancel()

    @commands.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def setleaderboardchannel(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        channel: discord.TextChannel,
    ) -> None:
        """Set the automatic leaderboard channel."""
        await self.bot.database.execute(
            "INSERT INTO leaderboard_settings (guild_id, channel_id, message_id) VALUES (?, ?, NULL) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id, message_id = NULL",
            (ctx.guild.id, channel.id),
        )
        await self.update_guild(ctx.guild.id)
        await ctx.send(embed=success_embed("Leaderboard channel set", f"Updates will appear in {channel.mention}."))

    @tasks.loop(minutes=10)
    async def refresh_leaderboards(self) -> None:
        """Refresh all configured displays periodically."""
        for row in await self.bot.database.fetchall("SELECT guild_id FROM leaderboard_settings"):
            await self.update_guild(int(row["guild_id"]))

    @refresh_leaderboards.before_loop
    async def before_refresh(self) -> None:
        await self.bot.wait_until_ready()

    async def update_guild(self, guild_id: int) -> None:
        """Create or edit a guild's leaderboard message."""
        setting = await self.bot.database.fetchone("SELECT channel_id, message_id FROM leaderboard_settings WHERE guild_id = ?", (guild_id,))
        guild = self.bot.get_guild(guild_id)
        if setting is None or guild is None:
            return
        channel = guild.get_channel(int(setting["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        rows = await self.bot.database.fetchall("SELECT user_id, xp, level FROM users WHERE guild_id = ? ORDER BY xp DESC, user_id ASC LIMIT 20", (guild_id,))
        text = "\n".join(f"**{i}.** <@{r['user_id']}> — Level {r['level']} • {r['xp']:,} XP" for i, r in enumerate(rows, 1)) or "No XP earned yet."
        embed = base_embed("🏆 Code Nexus Leaderboard", text)
        message = None
        if setting["message_id"]:
            try:
                message = await channel.fetch_message(int(setting["message_id"]))
            except discord.NotFound:
                pass
        if message:
            await message.edit(embed=embed)
        else:
            message = await channel.send(embed=embed)
            await self.bot.database.execute("UPDATE leaderboard_settings SET message_id = ? WHERE guild_id = ?", (message.id, guild_id))


async def setup(bot: HatsuneMikuBot) -> None:
    await bot.add_cog(LeaderboardDisplay(bot))
