"""Persistent XP, ranking, and level reward commands."""

from __future__ import annotations

import asyncio
import io
import logging
import random
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from database.database import Database, LevelProgress
from utils.embeds import base_embed, error_embed, success_embed

if TYPE_CHECKING:
    from bot import HatsuneMikuBot


LOGGER = logging.getLogger(__name__)
MAX_LEVEL = 500


class Leveling(commands.Cog):
    """Award message XP and expose member ranking commands."""

    def __init__(self, bot: HatsuneMikuBot) -> None:
        self.bot = bot

    @property
    def database(self) -> Database:
        """Return the bot's initialized persistence layer."""
        return self.bot.database

    async def award_message_xp(
        self,
        member: discord.Member,
        channel: discord.abc.Messageable,
    ) -> None:
        """Award cooldown-protected XP and announce a newly reached level."""
        progress = await self.database.update_member_xp(
            member.guild.id,
            member.id,
            random.randint(15, 25),
            enforce_cooldown=True,
        )
        if progress is None or progress.level == progress.previous_level:
            return
        display = self.bot.get_cog("LeaderboardDisplay")
        if display is not None:
            await display.update_guild(member.guild.id)
        await self._apply_role_reward(member, progress.level)
        embed = success_embed(
            "🎉 Level up!",
            f"{member.mention} reached **Level {progress.level}** "
            f"with **{progress.xp:,} XP**. Keep building!",
        )
        await channel.send(embed=embed)

    async def _apply_role_reward(self, member: discord.Member, level: int) -> None:
        reward = await self.database.fetchone(
            "SELECT role_id FROM role_rewards WHERE guild_id = ? AND level = ?",
            (member.guild.id, level),
        )
        if reward is None:
            return
        role = member.guild.get_role(int(reward["role_id"]))
        if role is None or role in member.roles:
            return
        try:
            await member.add_roles(role, reason=f"Reached Code Nexus level {level}")
        except discord.Forbidden:
            LOGGER.warning("Cannot assign reward role %s in guild %s.", role.id, member.guild.id)
        except discord.HTTPException:
            LOGGER.exception("Failed to assign level reward role.")

    @commands.command(aliases=["level"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def rank(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        member: discord.Member | None = None,
    ) -> None:
        """Render a member's rank card."""
        target = member or ctx.author
        if not isinstance(target, discord.Member) or ctx.guild is None:
            return
        progress, position = await self._member_progress(ctx.guild.id, target.id)
        try:
            avatar_bytes = await target.display_avatar.read()
            card = await asyncio.to_thread(
                self._build_rank_card,
                target.display_name,
                avatar_bytes,
                progress,
                position,
            )
        except (discord.HTTPException, OSError):
            LOGGER.exception("Rank card generation failed.")
            await ctx.send(embed=error_embed("I couldn't generate that rank card."))
            return
        await ctx.send(file=discord.File(card, filename=f"rank-{target.id}.png"))

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def leaderboard(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Show the top ten members by XP."""
        if ctx.guild is None:
            return
        rows = await self.database.fetchall(
            "SELECT user_id, xp, level FROM users WHERE guild_id = ? "
            "ORDER BY xp DESC, user_id ASC LIMIT 10",
            (ctx.guild.id,),
        )
        if not rows:
            await ctx.send(embed=base_embed("🏆 Leaderboard", "No XP has been earned yet."))
            return
        lines = [
            f"**{index}.** <@{row['user_id']}> — Level {row['level']} • {row['xp']:,} XP"
            for index, row in enumerate(rows, start=1)
        ]
        await ctx.send(embed=base_embed("🏆 Code Nexus Leaderboard", "\n".join(lines)))

    @commands.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def setlevel(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        member: discord.Member,
        level: commands.Range[int, 0, MAX_LEVEL],
    ) -> None:
        """Set a member's level using the standard XP curve."""
        if ctx.guild is None:
            return
        current, _ = await self._member_progress(ctx.guild.id, member.id)
        target_xp = self.database.xp_for_level(level)
        progress = await self.database.update_member_xp(
            ctx.guild.id,
            member.id,
            target_xp - current.xp,
        )
        assert progress is not None
        await self._apply_role_reward(member, progress.level)
        await ctx.send(embed=success_embed("Level updated", self._progress_message(member, progress)))

    @commands.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def addxp(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        member: discord.Member,
        amount: commands.Range[int, 1, 100_000],
    ) -> None:
        """Add XP to a member."""
        if ctx.guild is None:
            return
        progress = await self.database.update_member_xp(ctx.guild.id, member.id, amount)
        assert progress is not None
        if progress.level > progress.previous_level:
            await self._apply_role_reward(member, progress.level)
        await ctx.send(embed=success_embed("XP added", self._progress_message(member, progress)))

    @commands.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def removexp(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        member: discord.Member,
        amount: commands.Range[int, 1, 100_000],
    ) -> None:
        """Remove XP from a member without allowing a negative total."""
        if ctx.guild is None:
            return
        progress = await self.database.update_member_xp(ctx.guild.id, member.id, -amount)
        assert progress is not None
        await ctx.send(embed=success_embed("XP removed", self._progress_message(member, progress)))

    @commands.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def setlevelrole(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        level: commands.Range[int, 1, MAX_LEVEL],
        role: discord.Role,
    ) -> None:
        """Configure the role automatically granted at an exact level."""
        if ctx.guild is None or ctx.guild.me is None:
            return
        if role >= ctx.guild.me.top_role:
            await ctx.send(embed=error_embed("That role must be below my highest role."))
            return
        await self.database.execute(
            "INSERT INTO role_rewards (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (ctx.guild.id, level, role.id),
        )
        await ctx.send(
            embed=success_embed(
                "Level role saved",
                f"{role.mention} will be granted at Level **{level}**.",
            )
        )

    @commands.command()
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def removelevelrole(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        level: commands.Range[int, 1, MAX_LEVEL],
    ) -> None:
        """Remove the configured role reward for a level."""
        if ctx.guild is None:
            return
        await self.database.execute(
            "DELETE FROM role_rewards WHERE guild_id = ? AND level = ?",
            (ctx.guild.id, level),
        )
        await ctx.send(
            embed=success_embed(
                "Level role removed",
                f"The reward for Level **{level}** was removed.",
            )
        )

    async def _member_progress(self, guild_id: int, user_id: int) -> tuple[LevelProgress, int]:
        row = await self.database.fetchone(
            "SELECT xp, level FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        xp = int(row["xp"]) if row else 0
        level = int(row["level"]) if row else 0
        rank_row = await self.database.fetchone(
            "SELECT COUNT(*) + 1 AS position FROM users WHERE guild_id = ? "
            "AND (xp > ? OR (xp = ? AND user_id < ?))",
            (guild_id, xp, xp, user_id),
        )
        return LevelProgress(xp, level, level), int(rank_row["position"])

    @staticmethod
    def _progress_message(member: discord.Member, progress: LevelProgress) -> str:
        return (
            f"{member.mention} is Level **{progress.level}** "
            f"with **{progress.xp:,} XP**."
        )

    @staticmethod
    def _build_rank_card(
        name: str,
        avatar_bytes: bytes,
        progress: LevelProgress,
        position: int,
    ) -> io.BytesIO:
        """Build a dark, Miku-themed PNG rank card off the event loop."""
        image = Image.new("RGB", (900, 260), "#0D1117")
        draw = ImageDraw.Draw(image)
        primary = "#6E9EFF"
        draw.rounded_rectangle((18, 18, 882, 242), radius=24, fill="#161B22")
        draw.ellipse((50, 50, 210, 210), fill=primary)
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB").resize((146, 146))
        mask = Image.new("L", (146, 146), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 146, 146), fill=255)
        image.paste(avatar, (57, 57), mask)
        title_font = ImageFont.load_default(size=26)
        body_font = ImageFont.load_default(size=18)
        draw.text((245, 58), name[:28], font=title_font, fill="#F0F6FC")
        draw.text((245, 100), f"LEVEL {progress.level}     RANK #{position}", font=body_font, fill=primary)
        level_start = Database.xp_for_level(progress.level)
        level_end = Database.xp_for_level(progress.level + 1)
        ratio = (progress.xp - level_start) / max(1, level_end - level_start)
        draw.text((245, 144), f"{progress.xp:,} XP  •  {level_end - progress.xp:,} XP to next level", font=body_font, fill="#C9D1D9")
        draw.rounded_rectangle((245, 182, 830, 206), radius=12, fill="#30363D")
        draw.rounded_rectangle((245, 182, 245 + int(585 * ratio), 206), radius=12, fill=primary)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output


async def setup(bot: HatsuneMikuBot) -> None:
    """Load the cog."""
    await bot.add_cog(Leveling(bot))
