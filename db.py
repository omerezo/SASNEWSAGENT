import os
import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any

import psycopg2

from config import config


logger = logging.getLogger(__name__)


@dataclass
class UserSession:
    user_id: int
    state: str
    transcribed_text: Optional[str] = None
    article_ar: Optional[str] = None
    article_en: Optional[str] = None
    title_ar: Optional[str] = None
    title_en: Optional[str] = None
    excerpt_ar: Optional[str] = None
    excerpt_en: Optional[str] = None
    image_file_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Database:
    def __init__(self, conn=None):
        if conn:
            self.conn = conn
        else:
            if not config.database_url:
                raise ValueError("DATABASE_URL not set")
            logger.info("Connecting to PostgreSQL")
            self.conn = psycopg2.connect(config.database_url)
        self._init_tables()
    
    def _init_tables(self):
        with self.conn.cursor() as cur:
            # Create table with all needed columns
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id BIGINT PRIMARY KEY,
                    state VARCHAR(50) NOT NULL DEFAULT 'waiting_voice',
                    transcribed_text TEXT,
                    title_ar TEXT,
                    title_en TEXT,
                    content_ar TEXT,
                    content_en TEXT,
                    excerpt_ar TEXT,
                    excerpt_en TEXT,
                    image_file_id VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
    
    def get_session(self, user_id: int) -> Optional[UserSession]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM user_sessions WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                return UserSession(
                    user_id=row[0],
                    state=row[1],
                    transcribed_text=row[2],
                    article_ar=row[3],
                    article_en=row[4],
                    title_ar=row[5],
                    title_en=row[6],
                    excerpt_ar=row[7],
                    excerpt_en=row[8],
                    image_file_id=row[9],
                    created_at=row[10],
                    updated_at=row[11]
                )
            return None
    
    def create_session(self, user_id: int, state: str = "waiting_voice") -> UserSession:
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_sessions (user_id, state)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, updated_at = CURRENT_TIMESTAMP
                RETURNING user_id, state, created_at, updated_at
            """, (user_id, state))
            row = cur.fetchone()
            self.conn.commit()
            if row:
                return UserSession(
                    user_id=int(row[0]),
                    state=str(row[1]),
                    created_at=row[2],
                    updated_at=row[3]
                )
            return UserSession(user_id=user_id, state=state)
    
    def update_session(self, user_id: int, **kwargs) -> UserSession:
        if not kwargs:
            return self.get_session(user_id)
        
        set_cols = []
        values = []
        for key, value in kwargs.items():
            set_cols.append(f"{key} = %s")
            values.append(value)
        values.append(user_id)
        
        query = f"""
            UPDATE user_sessions 
            SET {', '.join(set_cols)}, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = %s
            RETURNING user_id, state, created_at, updated_at
        """
        with self.conn.cursor() as cur:
            cur.execute(query, values)
            row = cur.fetchone()
            self.conn.commit()
            if row:
                return UserSession(
                    user_id=int(row[0]),
                    state=str(row[1]),
                    created_at=row[2],
                    updated_at=row[3]
                )
        return self.get_session(user_id)
    
    def delete_session(self, user_id: int):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
            self.conn.commit()


_db = None

def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db