"""SQLite persistence layer for Code Nexus."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


@dataclass(frozen=True, slots=True)
class LevelProgress:
    """A member's XP state after an update."""

    xp: int
    level: int
    previous_level: int


class Database:
    """Owns the single SQLite connection used by the bot."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open and initialize the database connection."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA foreign_keys = ON")
        await self.connection.execute("PRAGMA journal_mode = WAL")
        await self.connection.execute("PRAGMA busy_timeout = 5000")
        await self.initialize()

    async def close(self) -> None:
        """Commit pending work and close the connection."""
        if self.connection is not None:
            await self.connection.commit()
            await self.connection.close()
            self.connection = None

    async def initialize(self) -> None:
        """Create all persistent tables and indexes."""
        connection = self._require_connection()
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
                level INTEGER NOT NULL DEFAULT 0 CHECK (level >= 0),
                last_xp_at TEXT,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS role_rewards (
                guild_id INTEGER NOT NULL,
                level INTEGER NOT NULL CHECK (level > 0),
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, level)
            );
            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                xp_reward INTEGER NOT NULL CHECK (xp_reward > 0),
                created_by INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS challenge_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leaderboard_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                evidence TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                reviewed_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                UNIQUE (challenge_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                welcome_channel_id INTEGER,
                leave_channel_id INTEGER,
                log_channel_id INTEGER,
                auto_role_id INTEGER,
                level_up_channel_id INTEGER,
                muted_role_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS music_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                webpage_url TEXT NOT NULL,
                requested_by INTEGER NOT NULL,
                duration_seconds INTEGER,
                UNIQUE (guild_id, position)
            );
            CREATE TABLE IF NOT EXISTS ai_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_users_guild_xp ON users (guild_id, xp DESC);
            CREATE INDEX IF NOT EXISTS idx_challenges_guild_week ON challenges (guild_id, week_start);
            CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings (guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_ai_messages_history
                ON ai_messages (guild_id, user_id, id DESC);
            """
        )
        await connection.commit()

    async def fetchone(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> aiosqlite.Row | None:
        """Return the first result for a parameterized query."""
        cursor = await self._require_connection().execute(query, parameters)
        return await cursor.fetchone()

    async def execute(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> None:
        """Run a parameterized modifying statement and commit it."""
        async with self._write_lock:
            connection = self._require_connection()
            await connection.execute(query, parameters)
            await connection.commit()

    async def fetchall(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[aiosqlite.Row]:
        """Return every result for a parameterized query."""
        cursor = await self._require_connection().execute(query, parameters)
        return await cursor.fetchall()

    async def update_member_xp(
        self,
        guild_id: int,
        user_id: int,
        xp_change: int,
        *,
        enforce_cooldown: bool = False,
    ) -> LevelProgress | None:
        """Atomically update a member's XP and optionally enforce the 60s cooldown."""
        async with self._write_lock:
            connection = self._require_connection()
            now = datetime.now(UTC)
            now_value = now.isoformat()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "SELECT xp, level, last_xp_at FROM users "
                    "WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
                row = await cursor.fetchone()
                current_xp = int(row["xp"]) if row else 0
                previous_level = int(row["level"]) if row else 0

                if enforce_cooldown and row and row["last_xp_at"]:
                    last_award = datetime.fromisoformat(str(row["last_xp_at"]))
                    if (now - last_award).total_seconds() < 60:
                        await connection.rollback()
                        return None

                updated_xp = max(0, current_xp + xp_change)
                updated_level = self.level_for_xp(updated_xp)
                await connection.execute(
                    """
                    INSERT INTO users (guild_id, user_id, xp, level, last_xp_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                        xp = excluded.xp,
                        level = excluded.level,
                        last_xp_at = excluded.last_xp_at
                    """,
                    (guild_id, user_id, updated_xp, updated_level, now_value),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

        return LevelProgress(updated_xp, updated_level, previous_level)

    async def record_ai_exchange(
        self,
        guild_id: int,
        user_id: int,
        prompt: str,
        response: str,
        history_limit: int = 12,
    ) -> None:
        """Persist an AI exchange while retaining only recent conversation turns."""
        async with self._write_lock:
            connection = self._require_connection()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await connection.executemany(
                    """
                    INSERT INTO ai_messages (guild_id, user_id, role, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        (guild_id, user_id, "user", prompt),
                        (guild_id, user_id, "assistant", response),
                    ),
                )
                await connection.execute(
                    """
                    DELETE FROM ai_messages
                    WHERE guild_id = ? AND user_id = ?
                      AND id NOT IN (
                          SELECT id FROM ai_messages
                          WHERE guild_id = ? AND user_id = ?
                          ORDER BY id DESC LIMIT ?
                      )
                    """,
                    (guild_id, user_id, guild_id, user_id, history_limit),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def clear_ai_history(self, guild_id: int, user_id: int) -> None:
        """Delete one member's persisted AI conversation history."""
        await self.execute(
            "DELETE FROM ai_messages WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

    @staticmethod
    def level_for_xp(xp: int) -> int:
        """Convert total XP to a level using a quadratic progression."""
        return int((xp / 100) ** 0.5)

    @staticmethod
    def xp_for_level(level: int) -> int:
        """Return the total XP required to reach a level."""
        return level * level * 100

    def _require_connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database connection is not initialized.")
        return self.connection

