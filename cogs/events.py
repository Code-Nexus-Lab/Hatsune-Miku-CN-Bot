"""Discord event listeners."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from cogs.leveling import Leveling

if TYPE_CHECKING:
    from bot import HatsuneMikuBot


LOGGER = logging.getLogger(__name__)


class Events(commands.Cog):
    """Route Discord events to feature cogs."""

    def __init__(self, bot: HatsuneMikuBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Award XP for each non-bot guild message, subject to cooldown."""
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.author, discord.Member):
            return
        leveling = self.bot.get_cog("Leveling")
        if not isinstance(leveling, Leveling):
            LOGGER.error("Leveling cog is unavailable; message XP skipped.")
            return
        await leveling.award_message_xp(message.author, message.channel)


async def setup(bot: HatsuneMikuBot) -> None:
    """Load the cog."""
    await bot.add_cog(Events(bot))
