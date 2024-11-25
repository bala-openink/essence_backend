import psycopg2
from psycopg2.extras import DictCursor
from typing import List, Dict, Optional
from lib.log import logger
from ..interfaces.database import FeedBatchRepository

class PostgreSQLFeedBatchRepository(FeedBatchRepository):
    """PostgreSQL implementation of feed batch operations"""
    def __init__(self, client):
        self._client = client
        self._cursor = client._cursor
        self._conn = client._conn

    def get_batch(self, batch_id: str) -> Optional[Dict]:
        try:
            self._cursor.execute("SELECT * FROM feed_batch WHERE batch_id = %s", (batch_id,))
            return self._cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting batch from PostgreSQL: {e}")
            return None

    def create_batch(self, batch_record: Dict) -> Optional[Dict]:
        try:
            self._cursor.execute("""
                INSERT INTO feed_batch (batch_id, status, start_time, total_feeds, completed_feeds)
                VALUES (%s, 'in_progress', %s, %s, 0)
            """, (batch_record['batch_id'], batch_record['start_time'], batch_record['total_feeds']))
            self._conn.commit()
            return batch_record
        except Exception as e:
            logger.error(f"Error creating batch in PostgreSQL: {e}")
            return None

    def mark_stage_complete(self, batch_id: str, stage: str, end_time: str) -> bool:
        try:
            self._cursor.execute(f"""
                UPDATE feed_batch
                SET {stage}_completion_time = %s
                WHERE batch_id = %s
            """, (end_time, batch_id))
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error marking stage complete in PostgreSQL: {e}")
            return False

    def update_stage_status(self, batch_id: str, stage: str, processed: int, skipped: int, errors: List[str]) -> bool:
        try:
            self._cursor.execute(f"""
                UPDATE feed_batch
                SET {stage}_processed = {stage}_processed + %s,
                    {stage}_skipped = {stage}_skipped + %s,
                    {stage}_errors = array_cat({stage}_errors, %s::text[])
                WHERE batch_id = %s
            """, (processed, skipped, errors, batch_id))
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating stage status in PostgreSQL: {e}")
            return False

    def increment_completed_feeds(self, batch_id: str, increment: int = 1) -> bool:
        try:
            self._cursor.execute("""
                UPDATE feed_batch
                SET completed_feeds = completed_feeds + %s
                WHERE batch_id = %s
            """, (increment, batch_id))
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error incrementing completed feeds in PostgreSQL: {e}")
            return False