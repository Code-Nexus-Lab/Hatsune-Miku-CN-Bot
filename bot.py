"""Code Nexus Discord bot entry point."""

import asyncio
import logging

import aiohttp
import discord
from discord.ext import commands

from config import BASE_DIR, Settings
from database.database import Database
from utils.embeds import error_embed
from utils.logger import configure_logging

LOGGER = logging.getLogger(__name__)
INITIAL_EXTENSIONS = (
    "cogs.utility",
    "cogs.leveling",
    "cogs.events",
    "cogs.ai",
    "cogs.music",
    "cogs.weekly",
    "cogs.leaderboard",
    "cogs.github",
)


class HatsuneMikuBot(commands.Bot):
    """Discord client with shared network and persistence resources."""

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.prefix),
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                replied_user=False,
            ),
        )
        self.settings = settings
        self.database = Database(settings.database_path)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        """Initialize shared resources before connecting to Discord."""
        await self.database.connect()
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)
        LOGGER.info("Loaded %d extension(s).", len(INITIAL_EXTENSIONS))

    async def close(self) -> None:
        """Release owned resources during a graceful shutdown."""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await self.database.close()
        await super().close()

    async def on_ready(self) -> None:
        """Log the completed Discord connection."""
        assert self.user is not None
        LOGGER.info("Logged in as %s (%s).", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Code Nexus developers",
            )
        )

    async def on_command_completion(self, ctx: commands.Context[commands.Bot]) -> None:
        """Log successfully executed prefix commands."""
        command_name = ctx.command.qualified_name if ctx.command else "unknown"
        guild_id = ctx.guild.id if ctx.guild else "DM"
        LOGGER.info("Command %s used by %s in %s.", command_name, ctx.author.id, guild_id)

    async def on_command_error(
        self,
        ctx: commands.Context[commands.Bot],
        error: commands.CommandError,
    ) -> None:
        """Convert expected command failures into safe user feedback."""
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=error_embed(f"Try again in {error.retry_after:.1f} seconds."))
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return
        if isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing argument: `{error.param.name}`. Use `{ctx.clean_prefix}help`."
            await ctx.send(embed=error_embed(message))
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(embed=error_embed("I couldn't understand that argument."))
            return
        LOGGER.exception("Unhandled command error", exc_info=error)
        await ctx.send(embed=error_embed("An unexpected error occurred. It has been logged."))


async def main() -> None:
    """Configure and start Hatsune Miku."""
    settings = Settings.from_environment()
    settings.validate()
    configure_logging(settings.log_level, BASE_DIR / "logs")
    bot = HatsuneMikuBot(settings)
    try:
        await bot.start(settings.discord_token, reconnect=True)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())

