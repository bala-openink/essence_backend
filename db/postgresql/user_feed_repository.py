from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from lib.log import logger
from ..interfaces.database import UserFeedRepository

class PostgreSQLUserFeedRepository(UserFeedRepository):
    def __init__(self, client):
        self._client = client
        self._cursor = client._cursor
        self._conn = client._conn

    def bulk_create(self, user_feeds: List[Dict[str, Any]]) -> None:
        """Bulk insert user feeds"""
        try:
            values = []
            for feed in user_feeds:
                # Validate required fields
                if not feed.get('user_id') or not feed.get('article_id'):
                    raise ValueError("user_id and article_id are required fields")

                values.append((
                    feed['user_id'],
                    feed['article_id'],
                    feed.get('title'),
                    feed.get('url'),
                    feed.get('domain'),
                    feed.get('image'),
                    feed.get('date_published'),
                    feed.get('summary_50'),
                    feed.get('summary_200'),
                    feed.get('audio_summary'),
                    json.dumps(feed.get('categories', {})),
                    feed.get('source_name'),
                    feed.get('type'),
                    feed.get('is_from_preferred_source'),
                    feed.get('score')
                ))

            self._cursor.executemany("""
                INSERT INTO user_feeds (
                    user_id, article_id, title, url, domain, image, 
                    date_published, summary_50, summary_200, audio_summary,
                    categories, source_name, type, is_from_preferred_source, score
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, article_id) DO NOTHING
            """, values)
            self._conn.commit()
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Error in bulk_create: {str(e)}")
            raise

    def get_user_feed(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get user's feed articles"""
        try:
            self._cursor.execute("""
                SELECT user_id, article_id, title, url, domain, image,
                       date_published, summary_50, summary_200, audio_summary,
                       categories, source_name, type, is_from_preferred_source, score
                FROM user_feeds
                WHERE user_id = %s
                ORDER BY date_published DESC, score DESC
                LIMIT %s OFFSET %s
            """, (user_id, limit, offset))
            
            results = self._cursor.fetchall()
            columns = [desc[0] for desc in self._cursor.description]
            
            return [
                {
                    columns[i]: value if not isinstance(value, str) or not value.startswith('{')
                    else json.loads(value)
                    for i, value in enumerate(row)
                }
                for row in results
            ]
            
        except Exception as e:
            logger.error(f"Error in get_user_feed: {str(e)}")
            raise

    def delete_old_feeds(
        self,
        user_id: str,
        before_date: str
    ) -> int:
        """Delete user's old feed entries"""
        try:
            self._cursor.execute("""
                DELETE FROM user_feeds
                WHERE user_id = %s
                AND date_published < %s
                RETURNING id
            """, (user_id, before_date))
            
            deleted_count = self._cursor.rowcount
            self._conn.commit()
            return deleted_count
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Error in delete_old_feeds: {str(e)}")
            raise