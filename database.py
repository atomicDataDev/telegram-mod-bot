import sqlite3
import threading
from datetime import datetime
from typing import Optional, List


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # Each operation opens a dedicated connection so the bot can safely
        # handle concurrent updates and background jobs.
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        # The entire schema is created automatically on first start.
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    group_id   INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    username   TEXT,
                    first_name TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (group_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_users_uname
                    ON users(group_id, username COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS pending (
                    group_id   INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    username   TEXT,
                    first_name TEXT,
                    joined_at  TEXT,
                    PRIMARY KEY (group_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS duel_stats (
                    group_id INTEGER NOT NULL,
                    user_id  INTEGER NOT NULL,
                    wins     INTEGER DEFAULT 0,
                    losses   INTEGER DEFAULT 0,
                    draws    INTEGER DEFAULT 0,
                    PRIMARY KEY (group_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS warns (
                    group_id INTEGER NOT NULL,
                    user_id  INTEGER NOT NULL,
                    count    INTEGER DEFAULT 0,
                    PRIMARY KEY (group_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS reputation (
                    group_id INTEGER NOT NULL,
                    user_id  INTEGER NOT NULL,
                    score    INTEGER DEFAULT 0,
                    PRIMARY KEY (group_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS rep_log (
                    group_id  INTEGER NOT NULL,
                    voter_id  INTEGER NOT NULL,
                    vote_date TEXT NOT NULL,
                    PRIMARY KEY (group_id, voter_id, vote_date)
                );

                CREATE TABLE IF NOT EXISTS chat_settings (
                    group_id      INTEGER PRIMARY KEY,
                    duels_enabled INTEGER DEFAULT 1,
                    strict_mode   INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id INTEGER PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS global_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
        print(f"[DB] Database is ready: {self.db_path}")

    # ═══════════ Users ═══════════
    # Core index of members already seen in the group.

    def upsert_user(self, gid, uid, username=None, first_name=None):
        with self.lock, self._conn() as c:
            c.execute(
                """INSERT INTO users (group_id,user_id,username,first_name,updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(group_id,user_id) DO UPDATE SET
                       username=excluded.username,
                       first_name=excluded.first_name,
                       updated_at=excluded.updated_at""",
                (gid, uid, username, first_name, datetime.now().isoformat()),
            )

    def find_by_username(self, gid, username) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM users WHERE group_id=? AND LOWER(username)=LOWER(?)",
                (gid, username),
            ).fetchone()
            return dict(r) if r else None

    def find_by_id(self, gid, uid) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM users WHERE group_id=? AND user_id=?",
                (gid, uid),
            ).fetchone()
            return dict(r) if r else None

    def remove_user(self, gid, uid):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM users WHERE group_id=? AND user_id=?", (gid, uid))

    def user_count(self, gid) -> int:
        with self._conn() as c:
            r = c.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE group_id=?", (gid,)
            ).fetchone()
            return r["cnt"] if r else 0

    # ═══════════ Full user cleanup ═══════════

    def purge_user(self, gid, uid):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM users WHERE group_id=? AND user_id=?", (gid, uid))
            c.execute("DELETE FROM pending WHERE group_id=? AND user_id=?", (gid, uid))
            c.execute("DELETE FROM warns WHERE group_id=? AND user_id=?", (gid, uid))
            c.execute("DELETE FROM duel_stats WHERE group_id=? AND user_id=?", (gid, uid))
            c.execute("DELETE FROM reputation WHERE group_id=? AND user_id=?", (gid, uid))
            c.execute("DELETE FROM rep_log WHERE group_id=? AND voter_id=?", (gid, uid))

    # ═══════════ Pending users ═══════════
    # Users who joined the group but have not been approved by an admin yet.

    def add_pending(self, gid, uid, username=None, first_name=None):
        with self.lock, self._conn() as c:
            c.execute(
                """INSERT INTO pending (group_id,user_id,username,first_name,joined_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(group_id,user_id) DO UPDATE SET
                       username=excluded.username,
                       first_name=excluded.first_name,
                       joined_at=excluded.joined_at""",
                (gid, uid, username, first_name, datetime.now().isoformat()),
            )

    def is_pending(self, gid, uid) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM pending WHERE group_id=? AND user_id=?",
                (gid, uid),
            ).fetchone()
            return r is not None

    def approve_user(self, gid, uid):
        with self.lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM pending WHERE group_id=? AND user_id=?", (gid, uid)
            ).fetchone()
            c.execute("DELETE FROM pending WHERE group_id=? AND user_id=?", (gid, uid))
            if row:
                c.execute(
                    """INSERT INTO users (group_id,user_id,username,first_name,updated_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(group_id,user_id) DO UPDATE SET
                           username=excluded.username,
                           first_name=excluded.first_name,
                           updated_at=excluded.updated_at""",
                    (gid, uid, row["username"], row["first_name"],
                     datetime.now().isoformat()),
                )

    def remove_pending(self, gid, uid):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM pending WHERE group_id=? AND user_id=?", (gid, uid))

    def get_pending(self, gid) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM pending WHERE group_id=? ORDER BY joined_at", (gid,)
            ).fetchall()
            return [dict(r) for r in rows]

    def pending_count(self, gid) -> int:
        with self._conn() as c:
            r = c.execute(
                "SELECT COUNT(*) AS cnt FROM pending WHERE group_id=?", (gid,)
            ).fetchone()
            return r["cnt"] if r else 0

    # ═══════════ Duels ═══════════
    # Per-group stats for wins, losses, and draws.

    def record_duel(self, gid, winner_id, loser_id, draw=False):
        with self.lock, self._conn() as c:
            for uid in (winner_id, loser_id):
                c.execute(
                    "INSERT OR IGNORE INTO duel_stats (group_id,user_id) VALUES (?,?)",
                    (gid, uid),
                )
            if draw:
                for uid in (winner_id, loser_id):
                    c.execute(
                        "UPDATE duel_stats SET draws=draws+1 "
                        "WHERE group_id=? AND user_id=?",
                        (gid, uid),
                    )
            else:
                c.execute(
                    "UPDATE duel_stats SET wins=wins+1 "
                    "WHERE group_id=? AND user_id=?",
                    (gid, winner_id),
                )
                c.execute(
                    "UPDATE duel_stats SET losses=losses+1 "
                    "WHERE group_id=? AND user_id=?",
                    (gid, loser_id),
                )

    def get_duel_stats(self, gid, uid) -> dict:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM duel_stats WHERE group_id=? AND user_id=?",
                (gid, uid),
            ).fetchone()
            return dict(r) if r else {"wins": 0, "losses": 0, "draws": 0}

    def get_duel_leaderboard(self, gid, limit=10) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT d.user_id, d.wins, d.losses, d.draws,
                          u.first_name, u.username
                   FROM duel_stats d
                   LEFT JOIN users u ON d.group_id=u.group_id AND d.user_id=u.user_id
                   WHERE d.group_id=? AND (d.wins+d.losses+d.draws)>0
                   ORDER BY d.wins DESC, d.losses ASC
                   LIMIT ?""",
                (gid, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ═══════════ Warnings ═══════════
    # Warnings are accumulated per group and used for automatic bans.

    def add_warn(self, gid, uid) -> int:
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO warns (group_id,user_id,count) VALUES (?,?,1) "
                "ON CONFLICT(group_id,user_id) DO UPDATE SET count=count+1",
                (gid, uid),
            )
            r = c.execute(
                "SELECT count FROM warns WHERE group_id=? AND user_id=?",
                (gid, uid),
            ).fetchone()
            return r["count"] if r else 1

    def get_warns(self, gid, uid) -> int:
        with self._conn() as c:
            r = c.execute(
                "SELECT count FROM warns WHERE group_id=? AND user_id=?",
                (gid, uid),
            ).fetchone()
            return r["count"] if r else 0

    def reset_warns(self, gid, uid):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM warns WHERE group_id=? AND user_id=?", (gid, uid))

    def reset_all_warns(self, gid) -> int:
        with self.lock, self._conn() as c:
            r = c.execute(
                "SELECT COUNT(*) AS cnt FROM warns WHERE group_id=? AND count>0",
                (gid,),
            ).fetchone()
            affected = r["cnt"] if r else 0
            c.execute("DELETE FROM warns WHERE group_id=?", (gid,))
            return affected

    # ═══════════ Reputation ═══════════
    # Reputation and vote log are split to enforce one vote per day.

    def change_rep(self, gid, uid, delta: int):
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO reputation (group_id,user_id,score) VALUES (?,?,?) "
                "ON CONFLICT(group_id,user_id) DO UPDATE SET score=score+?",
                (gid, uid, delta, delta),
            )

    def get_rep(self, gid, uid) -> int:
        with self._conn() as c:
            r = c.execute(
                "SELECT score FROM reputation WHERE group_id=? AND user_id=?",
                (gid, uid),
            ).fetchone()
            return r["score"] if r else 0

    def get_rep_leaderboard(self, gid, limit=10) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                """SELECT r.user_id, r.score,
                          u.first_name, u.username
                   FROM reputation r
                   LEFT JOIN users u ON r.group_id=u.group_id AND r.user_id=u.user_id
                   WHERE r.group_id=? AND r.score != 0
                   ORDER BY r.score DESC
                   LIMIT ?""",
                (gid, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def can_vote_today(self, gid, voter_id) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM rep_log "
                "WHERE group_id=? AND voter_id=? AND vote_date=?",
                (gid, voter_id, today),
            ).fetchone()
            return r is None

    def record_vote(self, gid, voter_id):
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO rep_log (group_id,voter_id,vote_date) "
                "VALUES (?,?,?)",
                (gid, voter_id, today),
            )

    # ═══════════ Chat settings ═══════════
    # Group-level flags: duel mode and strict moderation.

    def are_duels_enabled(self, gid) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT duels_enabled FROM chat_settings WHERE group_id=?",
                (gid,),
            ).fetchone()
            return bool(r["duels_enabled"]) if r else True

    def set_duels_enabled(self, gid, enabled: bool):
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO chat_settings (group_id,duels_enabled) VALUES (?,?) "
                "ON CONFLICT(group_id) DO UPDATE SET duels_enabled=excluded.duels_enabled",
                (gid, int(enabled)),
            )

    def is_strict_enabled(self, gid) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT strict_mode FROM chat_settings WHERE group_id=?",
                (gid,),
            ).fetchone()
            return bool(r["strict_mode"]) if r else False

    def set_strict_enabled(self, gid, enabled: bool):
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO chat_settings (group_id,strict_mode) VALUES (?,?) "
                "ON CONFLICT(group_id) DO UPDATE SET strict_mode=excluded.strict_mode",
                (gid, int(enabled)),
            )


    # ═══════════ Bot admins ═══════════
    # These are trusted bot operators, not Telegram chat admins.

    def add_bot_admin(self, user_id: int):
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)",
                (user_id,),
            )

    def remove_bot_admin(self, user_id: int):
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM bot_admins WHERE user_id=?", (user_id,))

    def is_bot_admin(self, user_id: int) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,)
            ).fetchone()
            return r is not None

    def get_bot_admins(self) -> List[int]:
        with self._conn() as c:
            rows = c.execute("SELECT user_id FROM bot_admins").fetchall()
            return [r["user_id"] for r in rows]

    # ═══════════ Global settings ═══════════
    # Global values edited via /config in private chat.

    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        with self._conn() as c:
            r = c.execute(
                "SELECT value FROM global_settings WHERE key=?", (key,)
            ).fetchone()
            return r["value"] if r else default

    def set_setting(self, key: str, value: str):
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO global_settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_all_settings(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT key, value FROM global_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}
