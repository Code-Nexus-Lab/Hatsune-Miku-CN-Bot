"""Consistent Discord embed builders."""

from datetime import datetime

import discord

from utils.constants import EMBED_FOOTER, ERROR_COLOR, PRIMARY_COLOR, SUCCESS_COLOR


def base_embed(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color = PRIMARY_COLOR,
) -> discord.Embed:
    """Return an embed using the Code Nexus visual identity."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now().astimezone(),
    )
    embed.set_footer(text=EMBED_FOOTER)
    return embed


def success_embed(title: str, description: str) -> discord.Embed:
    """Return a success-styled embed."""
    return base_embed(title, description, color=SUCCESS_COLOR)


def error_embed(description: str) -> discord.Embed:
    """Return a concise error embed safe to show to users."""
    return base_embed("Something went wrong", description, color=ERROR_COLOR)

