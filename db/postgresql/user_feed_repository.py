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

                # Convert categories to list if it's not already
                categories = feed.get('categories', [])
                if not isinstance(categories, list):
                    categories = list(categories) if categories else []

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
                    categories,  # PostgreSQL will automatically handle Python list to SQL array conversion
                    feed.get('source_name'),
                    feed.get('type'),
                    feed.get('is_from_preferred_source'),
                    feed.get('score'),
                    feed.get('importance_score')
                ))

            self._cursor.executemany("""
                INSERT INTO user_feed (
                    user_id, article_id, title, url, domain, image, 
                    date_published, summary_50, summary_200, audio_summary,
                    categories, source_name, type, is_from_preferred_source, score, importance_score
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, article_id) DO NOTHING
            """, values)
            self._conn.commit()
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Error in bulk_create: {str(e)}")
            raise

    def delete_old_feeds(
        self,
        user_id: str,
        before_date: str
    ) -> int:
        """Delete user's old feed entries"""
        try:
            self._cursor.execute("""
                DELETE FROM user_feed
                WHERE user_id = %s
                AND date_created < %s
                RETURNING id
            """, (user_id, before_date))
            
            deleted_count = self._cursor.rowcount
            self._conn.commit()
            return deleted_count
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Error in delete_old_feeds: {str(e)}")
            raise

    def get_latest_news(
        self,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 20,
        preferred_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get latest unsent news for user"""
        # TODO: Add min score and min importance score filter to remove low relevance and low importance articles
        try:
            query = """
                SELECT user_id, article_id, title, url, domain, image,
                       date_published, summary_50, summary_200, audio_summary,
                       categories, source_name, type, is_from_preferred_source, score, importance_score, date_created
                FROM user_feed
                WHERE user_id = %s
                AND score >= 0 -- Filter out articles with negative scores to remove low relevance articles
                AND sent_to_user = FALSE
                AND is_from_preferred_source = %s
            """
            params = [user_id, preferred_only]

            if start_date:
                query += " AND date_created >= %s"
                params.append(start_date)
            if end_date:
                query += " AND date_created <= %s"
                params.append(end_date)

            query += " ORDER BY score DESC, date_created DESC LIMIT %s"
            params.append(limit)

            self._cursor.execute(query, params)
            return self._cursor.fetchall()

        except Exception as e:
            logger.error(f"Error in get_latest_news: {str(e)}")
            raise

    def mark_feeds_as_sent(self, user_id: str, article_ids: List[str]) -> None:
        """Mark feeds as sent to user"""
        try:
            self._cursor.execute("""
                UPDATE user_feed
                SET sent_to_user = TRUE
                WHERE user_id = %s AND article_id = ANY(%s)
            """, (user_id, article_ids))
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Error in mark_feeds_as_sent: {str(e)}")
            raise

    def get_articles_between_dates(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Get articles created between given dates"""
        try:
            self._cursor.execute("""
                SELECT DISTINCT article_id, title, summary_200
                FROM user_feed
                WHERE date_created BETWEEN %s AND %s
            """, (start_date, end_date))
            return self._cursor.fetchall()
        except Exception as e:
            logger.error(f"Error in get_articles_between_dates: {str(e)}")
            raise

    def update_importance_scores(self, article_scores: List[Dict[str, Any]]) -> None:
        """
        Bulk update importance scores for articles
        Args:
            article_scores: List of dicts with article_id and importance_score
            Example: [{"article_id": "123", "importance_score": 75}, ...]
        """
        try:
            # Extract arrays for single query
            article_ids = [score['article_id'] for score in article_scores]
            scores = [score['importance_score'] for score in article_scores]
            
            self._cursor.execute("""
                UPDATE user_feed
                SET importance_score = tmp.score
                FROM (
                    SELECT unnest(%s::text[]) as article_id, 
                           unnest(%s::float[]) as score
                ) tmp
                WHERE user_feed.article_id = tmp.article_id
            """, (article_ids, scores))
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            logger.error(f"Error in update_importance_scores: {str(e)}")
            raise