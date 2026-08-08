"""Weekly programming challenge workflow."""

from datetime import UTC, datetime, timedelta

import discord
from discord.ext import commands

from utils.embeds import base_embed, error_embed, success_embed


def current_week() -> str:
    """Return this week's UTC Monday date."""
    today = datetime.now(UTC).date()
    return (today - timedelta(days=today.weekday())).isoformat()


class Weekly(commands.Cog):
    """Create, publish, submit, approve, and reset weekly challenges."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="challenge", invoke_without_command=True)
    @commands.guild_only()
    async def challenge(self, ctx: commands.Context) -> None:
        """Show the active weekly challenges."""
        await self.list_challenges(ctx)

    @challenge.command(name="channel")
    @commands.has_guild_permissions(manage_guild=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set where admins publish new challenges."""
        await self.bot.database.execute(
            "INSERT INTO challenge_settings (guild_id, channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            (ctx.guild.id, channel.id),
        )
        await ctx.send(embed=success_embed("Challenge channel set", f"Publishing channel: {channel.mention}"))

    @challenge.command()
    @commands.has_guild_permissions(manage_guild=True)
    async def create(self, ctx: commands.Context, title: str, xp: int, *, description: str) -> None:
        """Create and post a challenge in the configured channel."""
        if not 1 <= xp <= 100_000 or len(title) > 100 or len(description) > 1_500:
            await ctx.send(embed=error_embed("Use 1–100,000 XP, a 100-character title, and a 1,500-character description."))
            return
        setting = await self.bot.database.fetchone("SELECT channel_id FROM challenge_settings WHERE guild_id = ?", (ctx.guild.id,))
        channel = ctx.guild.get_channel(int(setting["channel_id"])) if setting else None
        if not isinstance(channel, discord.TextChannel):
            await ctx.send(embed=error_embed("Configure a challenge channel first with the channel subcommand."))
            return
        await self.bot.database.execute(
            "INSERT INTO challenges (guild_id, title, description, xp_reward, created_by, week_start) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.guild.id, title, description, xp, ctx.author.id, current_week()),
        )
        row = await self.bot.database.fetchone("SELECT last_insert_rowid() AS id")
        embed = base_embed(f"🏁 Weekly Challenge #{row['id']}: {title}", description)
        embed.add_field(name="Reward", value=f"{xp:,} XP")
        embed.add_field(name="Submit", value=f"challenge complete {row['id']} <evidence>")
        await channel.send(embed=embed)
        await ctx.send(embed=success_embed("Challenge published", f"Posted in {channel.mention}."))

    @challenge.command(name="list")
    async def list_challenges(self, ctx: commands.Context) -> None:
        """List the active weekly challenges."""
        rows = await self.bot.database.fetchall("SELECT id, title, xp_reward FROM challenges WHERE guild_id = ? AND week_start = ? ORDER BY id", (ctx.guild.id, current_week()))
        description = "\n".join(f"#{r['id']} — {r['title']} ({r['xp_reward']:,} XP)" for r in rows) or "No active challenges this week."
        await ctx.send(embed=base_embed("🏁 This Week's Challenges", description))

    @challenge.command()
    async def complete(self, ctx: commands.Context, challenge_id: int, *, evidence: str) -> None:
        """Submit evidence for review."""
        challenge = await self.bot.database.fetchone("SELECT id FROM challenges WHERE id = ? AND guild_id = ? AND week_start = ?", (challenge_id, ctx.guild.id, current_week()))
        if challenge is None or not evidence.strip():
            await ctx.send(embed=error_embed("Provide evidence for an active challenge."))
            return
        try:
            await self.bot.database.execute("INSERT INTO submissions (challenge_id, user_id, evidence) VALUES (?, ?, ?)", (challenge_id, ctx.author.id, evidence[:1_500]))
        except Exception:
            await ctx.send(embed=error_embed("You already submitted this challenge."))
            return
        await ctx.send(embed=success_embed("Submission received", "An administrator will review it."))

    @challenge.command()
    @commands.has_guild_permissions(manage_guild=True)
    async def approve(self, ctx: commands.Context, challenge_id: int, member: discord.Member) -> None:
        """Approve a submission and grant XP."""
        row = await self.bot.database.fetchone("SELECT s.id, c.xp_reward FROM submissions s JOIN challenges c ON c.id = s.challenge_id WHERE s.challenge_id = ? AND s.user_id = ? AND s.status = 'pending' AND c.guild_id = ?", (challenge_id, member.id, ctx.guild.id))
        if row is None:
            await ctx.send(embed=error_embed("No pending submission was found."))
            return
        await self.bot.database.execute("UPDATE submissions SET status = 'approved', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (ctx.author.id, row["id"]))
        progress = await self.bot.database.update_member_xp(ctx.guild.id, member.id, int(row["xp_reward"]))
        await ctx.send(embed=success_embed("Approved", f"{member.mention} received {row['xp_reward']:,} XP and is Level {progress.level}."))

    @challenge.command()
    @commands.has_guild_permissions(manage_guild=True)
    async def delete(self, ctx: commands.Context, challenge_id: int) -> None:
        """Delete a challenge and its submissions."""
        await self.bot.database.execute("DELETE FROM challenges WHERE id = ? AND guild_id = ?", (challenge_id, ctx.guild.id))
        await ctx.send(embed=success_embed("Challenge deleted", f"Removed challenge #{challenge_id}."))


async def setup(bot: commands.Bot) -> None:
    """Load the cog."""
    await bot.add_cog(Weekly(bot))
