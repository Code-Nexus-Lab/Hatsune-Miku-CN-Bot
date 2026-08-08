"""Groq-powered programming assistant commands and mention replies."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from time import monotonic
from typing import TYPE_CHECKING, TypedDict

import aiohttp
import discord
from discord.ext import commands

from utils.embeds import base_embed, error_embed, success_embed

if TYPE_CHECKING:
    from bot import HatsuneMikuBot


LOGGER = logging.getLogger(__name__)
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
HISTORY_LIMIT = 12
MAX_PROMPT_LENGTH = 1_500
RATE_LIMIT_SECONDS = 15
SYSTEM_PROMPT = (
    "You are Hatsune Miku, the cheerful, professional AI assistant for the "
    "Code Nexus programming community. Give accurate, practical programming "
    "help. Prefer concise explanations, safe code, and clear next steps. "
    "When uncertain, say so. Do not claim to run code, access private data, "
    "or perform actions you cannot perform."
    "keep your clean amd small"
)


class ChatMessage(TypedDict):
    """A Groq-compatible chat message."""

    role: str
    content: str


class AI(commands.Cog):
    """Provide conversational programming help through Groq."""

    def __init__(self, bot: HatsuneMikuBot) -> None:
        self.bot = bot
        self._last_request: defaultdict[tuple[int, int], float] = defaultdict(float)
        self._request_locks: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 8, commands.BucketType.user)
    async def chat(
        self,
        ctx: commands.Context[HatsuneMikuBot],
        *,
        prompt: str | None = None,
    ) -> None:
        """Ask Hatsune Miku a programming question."""
        if prompt is None:
            await ctx.send(
                embed=base_embed(
                    "💬 Chat with Hatsune Miku",
                    f"Ask with `{ctx.clean_prefix}chat <question>`, or mention me. "
                    f"Use `{ctx.clean_prefix}chat clear` to delete your chat history.",
                )
            )
            return
        await self._answer(ctx.author, ctx.guild, ctx.channel, prompt)

    @chat.command(name="clear")
    @commands.guild_only()
    async def clear_history(self, ctx: commands.Context[HatsuneMikuBot]) -> None:
        """Delete the caller's stored conversation history for this server."""
        if ctx.guild is None:
            return
        await self.bot.database.clear_ai_history(ctx.guild.id, ctx.author.id)
        await ctx.send(
            embed=success_embed(
                "Chat history cleared",
                "Your Hatsune Miku conversation history for this server was deleted.",
            )
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Reply when the bot is mentioned in a guild message."""
        if message.author.bot or message.guild is None or self.bot.user is None:
            return
        if not self.bot.user.mentioned_in(message):
            return
        prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        if not prompt:
            await message.reply(
                embed=base_embed(
                    "💬 Hi! I'm Hatsune Miku",
                    f"Mention me with a question, or use "
                    f"`{self.bot.settings.prefix}chat <question>`.",
                ),
                mention_author=False,
            )
            return
        if not isinstance(message.author, discord.Member):
            return
        await self._answer(message.author, message.guild, message.channel, prompt)

    async def _answer(
        self,
        member: discord.Member,
        guild: discord.Guild | None,
        channel: discord.abc.Messageable,
        prompt: str,
    ) -> None:
        """Validate, rate-limit, and fulfill an AI response request."""
        if guild is None:
            return
        clean_prompt = prompt.strip()
        if not clean_prompt:
            await channel.send(embed=error_embed("Please include a question or message."))
            return
        if len(clean_prompt) > MAX_PROMPT_LENGTH:
            await channel.send(
                embed=error_embed(
                    f"Keep your message under {MAX_PROMPT_LENGTH:,} characters."
                )
            )
            return
        if not self.bot.settings.groq_api_key:
            await channel.send(
                embed=error_embed(
                    "AI chat is not configured. An administrator must set GROQ_API_KEY."
                )
            )
            return

        key = (guild.id, member.id)
        async with self._request_locks[key]:
            elapsed = monotonic() - self._last_request[key]
            if elapsed < RATE_LIMIT_SECONDS:
                await channel.send(
                    embed=error_embed(
                        f"Please wait {RATE_LIMIT_SECONDS - elapsed:.0f} seconds "
                        "before another AI request."
                    )
                )
                return
            self._last_request[key] = monotonic()

            async with channel.typing():
                answer = await self._request_completion(guild.id, member.id, clean_prompt)
            if answer is None:
                await channel.send(
                    embed=error_embed(
                        "I couldn't reach the AI service right now. Please try again soon."
                    )
                )
                return
            await self.bot.database.record_ai_exchange(
                guild.id,
                member.id,
                clean_prompt,
                answer,
                HISTORY_LIMIT,
            )
            await self._send_answer(channel, answer)

    async def _request_completion(
        self,
        guild_id: int,
        user_id: int,
        prompt: str,
    ) -> str | None:
        """Call Groq's OpenAI-compatible chat completions endpoint."""
        rows = await self.bot.database.fetchall(
            """
            SELECT role, content FROM (
                SELECT role, content, id FROM ai_messages
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
            """,
            (guild_id, user_id, HISTORY_LIMIT),
        )
        messages: list[ChatMessage] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in rows
        )
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.bot.settings.groq_model,
            "messages": messages,
            "temperature": 0.6,
            "max_completion_tokens": 700,
            "user": f"discord-{guild_id}-{user_id}",
        }
        headers = {
            "Authorization": f"Bearer {self.bot.settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        session = self.bot.http_session
        if session is None:
            LOGGER.error("AI request attempted before the HTTP session was initialized.")
            return None
        try:
            async with session.post(
                GROQ_CHAT_URL,
                json=payload,
                headers=headers,
            ) as response:
                response_data = await response.json(content_type=None)
                if response.status != 200:
                    LOGGER.warning(
                        "Groq returned HTTP %s: %s",
                        response.status,
                        response_data,
                    )
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            LOGGER.exception("Groq request failed.")
            return None

        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            LOGGER.error("Groq returned an unexpected response: %s", response_data)
            return None
        if not isinstance(content, str) or not content.strip():
            LOGGER.error("Groq returned an empty completion.")
            return None
        return content.strip()

    @staticmethod
    async def _send_answer(
        channel: discord.abc.Messageable,
        answer: str,
    ) -> None:
        """Send a long model response as a sequence of readable embeds."""
        chunks = [answer[index:index + 3_900] for index in range(0, len(answer), 3_900)]
        for index, chunk in enumerate(chunks, start=1):
            title = (
                "🎤 Hatsune Miku"
                if len(chunks) == 1
                else f"🎤 Hatsune Miku ({index}/{len(chunks)})"
            )
            await channel.send(embed=base_embed(title, chunk))


async def setup(bot: HatsuneMikuBot) -> None:
    """Load the cog."""
    await bot.add_cog(AI(bot))
