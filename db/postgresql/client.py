import psycopg2
from psycopg2.extensions import connection as psycopg2_connection
from psycopg2.extensions import cursor as psycopg2_cursor
from psycopg2.extras import DictCursor
from typing import Optional, Any

from lib.log import logger
from ..interfaces.database import DatabaseClient
import config
import constants 
from services import utilities

class PostgreSQLClient(DatabaseClient):
    """PostgreSQL client management"""
    
    def __init__(self, local: bool = False, stage: str = constants.STAGE_LOCAL):
        self.local = local
        self.stage = stage
        self._conn: Optional[psycopg2_connection] = None
        self._cursor: Optional[psycopg2_cursor] = None
        self._environment = config.ENVIRONMENT
        
    def connect(self) -> 'PostgreSQLClient':
        try:
            if self._environment == 'LOCAL':
                pg_password = config.PG_PASSWORD
            else:
                pg_password = utilities.get_secret(secret_key='PG_PASSWORD', default_value=config.PG_PASSWORD)

            database_name = f"{config.PG_DATABASE}_{self.stage}"

            connection_params = {
                'dbname': database_name,
                'user': config.PG_USER,
                'password': pg_password,
                'host': config.PG_HOST,
                'port': config.PG_PORT
            }
            
            self._conn = psycopg2.connect(**connection_params)
            self._cursor = self._conn.cursor(cursor_factory=DictCursor)
            
            # Create tables if they don't exist
            self._create_tables()
            return self
            
        except Exception as e:
            logger.error(f"Error connecting to PostgreSQL: {str(e)}")
            raise
            
    def disconnect(self) -> None:
        if self._cursor:
            self._cursor.close()
        if self._conn:
            self._conn.close()
        self._cursor = None
        self._conn = None

    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed
        
    def _create_tables(self):
        """Create necessary tables if they don't exist"""
        if self._cursor:
            self._cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_feed (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                article_id VARCHAR(255) NOT NULL,
                title TEXT,
                url TEXT,
                domain VARCHAR(255),
                image TEXT,
                date_published TIMESTAMP WITH TIME ZONE,
                summary_50 TEXT,
                summary_200 TEXT,
                audio_summary TEXT,
                categories TEXT[],
                source_name VARCHAR(255),
                type VARCHAR(255),
                is_from_preferred_source BOOLEAN,
                score FLOAT,
                sent_to_user BOOLEAN DEFAULT FALSE,
                date_created TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, article_id)
            );
            
            -- Primary index for date-based queries with score
            CREATE INDEX IF NOT EXISTS idx_user_feed_date_published_score 
            ON user_feed(user_id, date_published DESC, score DESC);
                                 
            -- Primary index for date-based queries with score
            CREATE INDEX IF NOT EXISTS idx_user_feed_date_created_score 
            ON user_feed(user_id, date_created DESC, score DESC);
            """)
        if self._conn:
            self._conn.commit()