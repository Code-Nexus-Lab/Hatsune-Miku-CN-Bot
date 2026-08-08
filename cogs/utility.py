"""Core informational commands for Hatsune Miku."""

from time import monotonic

import discord
from discord.ext import commands

from utils.constants import BOT_NAME
from utils.embeds import base_embed


class Utility(commands.Cog):
    """General commands useful in every Code Nexus server."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.started_at = monotonic()

    @commands.command(name="help")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def help_command(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the currently available command groups."""
        prefix = ctx.clean_prefix
        embed = base_embed(
            "🌐 Hatsune Miku Command Guide",
            "Code Nexus's cheerful AI assistant is online.",
        )
        embed.add_field(
            name="Core",
            value=(
                f"`{prefix}help`, `{prefix}about`, `{prefix}ping`, "
                f"`{prefix}uptime`, `{prefix}userinfo`, `{prefix}serverinfo`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Leveling",
            value="Use `!rank` / `!level` or `!leaderboard` to view progress.",
            inline=False,
        )
        embed.add_field(
            name="AI assistant",
            value=(
                f"Use `{prefix}chat <question>`, mention me, or "
                f"`{prefix}chat clear`."
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def ping(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the WebSocket latency."""
        latency = round(self.bot.latency * 1000)
        await ctx.send(embed=base_embed("🏓 Pong!", f"Latency: **{latency} ms**"))

    @commands.command()
    async def about(self, ctx: commands.Context[commands.Bot]) -> None:
        """Describe the bot's purpose."""
        embed = base_embed(
            f"✨ About {BOT_NAME}",
            "The official AI assistant for Code Nexus: helping programmers learn, build, and collaborate.",
        )
        embed.add_field(name="Built with", value="Python • discord.py • SQLite")
        await ctx.send(embed=embed)

    @commands.command()
    async def uptime(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show how long this process has been online."""
        seconds = int(monotonic() - self.started_at)
        await ctx.send(
            embed=base_embed("⏱️ Uptime", f"Online for **{seconds:,} seconds**.")
        )

    @commands.command()
    async def userinfo(
        self,
        ctx: commands.Context[commands.Bot],
        member: discord.Member | None = None,
    ) -> None:
        """Display information about a server member."""
        member = member or ctx.author
        if not isinstance(member, discord.Member):
            return
        embed = base_embed(f"👤 {member.display_name}")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=str(member.id))
        joined = discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown"
        embed.add_field(name="Joined", value=joined)
        embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "D"))
        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context[commands.Bot]) -> None:
        """Display a concise server summary."""
        guild = ctx.guild
        if guild is None:
            return
        embed = base_embed(f"🏠 {guild.name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Members", value=f"{guild.member_count:,}")
        embed.add_field(name="Channels", value=str(len(guild.channels)))
        embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, "D"))
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    """Load the cog."""
    await bot.add_cog(Utility(bot))

