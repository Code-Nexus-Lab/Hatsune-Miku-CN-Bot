"""GitHub REST API commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from discord.ext import commands

from utils.embeds import base_embed, error_embed

if TYPE_CHECKING:
    from bot import HatsuneMikuBot


class GitHub(commands.Cog):
    """Show public GitHub profile, organization, and repository data."""

    def __init__(self, bot: HatsuneMikuBot) -> None:
        self.bot = bot

    async def _get(self, path: str) -> dict | list | None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.bot.settings.github_token:
            headers["Authorization"] = f"Bearer {self.bot.settings.github_token}"
        try:
            async with self.bot.http_session.get(f"https://api.github.com{path}", headers=headers) as response:
                if response.status != 200:
                    return None
                return await response.json()
        except aiohttp.ClientError:
            return None

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def github(self, ctx: commands.Context[HatsuneMikuBot], username: str) -> None:
        """Show public GitHub profile statistics."""
        data = await self._get(f"/users/{username}")
        if not isinstance(data, dict):
            await ctx.send(embed=error_embed("GitHub user not found or API unavailable."))
            return
        embed = base_embed(f"🐙 GitHub: {data['login']}", data.get("bio") or "No bio provided.")
        embed.set_thumbnail(url=data["avatar_url"])
        embed.add_field(name="Repositories", value=str(data["public_repos"]))
        embed.add_field(name="Followers", value=str(data["followers"]))
        embed.add_field(name="Following", value=str(data["following"]))
        embed.add_field(name="Profile", value=data["html_url"], inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    async def org(self, ctx: commands.Context[HatsuneMikuBot], *, organization: str) -> None:
        """Show GitHub organization stats and top public repositories."""
        slug = organization.strip().replace(" ", "-")
        data = await self._get(f"/orgs/{slug}")
        repos = await self._get(f"/orgs/{slug}/repos?sort=updated&per_page=5")
        if not isinstance(data, dict):
            await ctx.send(embed=error_embed("GitHub organization not found. Use its GitHub organization name."))
            return
        embed = base_embed(f"🏢 GitHub Organization: {data['login']}", data.get("description") or "No description provided.")
        embed.set_thumbnail(url=data["avatar_url"])
        embed.add_field(name="Public repos", value=str(data["public_repos"]))
        embed.add_field(name="Followers", value=str(data["followers"]))
        if isinstance(repos, list):
            embed.add_field(name="Recent repositories", value="\n".join(f"• [{r['name']}]({r['html_url']}) ⭐ {r['stargazers_count']}" for r in repos) or "None", inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    async def repo(self, ctx: commands.Context[HatsuneMikuBot], repository: str) -> None:
        """Show repository details for owner/repository."""
        if repository.count("/") != 1:
            await ctx.send(embed=error_embed("Use owner/repository."))
            return
        data = await self._get(f"/repos/{repository}")
        if not isinstance(data, dict):
            await ctx.send(embed=error_embed("Repository not found."))
            return
        embed = base_embed(f"📦 {data['full_name']}", data.get("description") or "No description provided.")
        embed.add_field(name="Stars", value=str(data["stargazers_count"]))
        embed.add_field(name="Forks", value=str(data["forks_count"]))
        embed.add_field(name="Open issues", value=str(data["open_issues_count"]))
        embed.add_field(name="Language", value=data.get("language") or "Unknown")
        embed.add_field(name="URL", value=data["html_url"], inline=False)
        await ctx.send(embed=embed)


async def setup(bot: HatsuneMikuBot) -> None:
    await bot.add_cog(GitHub(bot))
