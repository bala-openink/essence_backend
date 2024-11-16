# db/factory.py

from typing import Optional
import config
from .dynamodb.client import DynamoDBClient
from .opensearch.client import OpenSearchClient
from .postgresql.client import PostgreSQLClient
from .dynamodb.user_repository import DynamoDBUserRepository
from .opensearch.article_repository import OpenSearchArticleRepository
from .dynamodb.repository import DynamoDBRepository
from .dynamodb.feed_batch_repository import DynamoDBFeedBatchRepository
from .postgresql.user_feed_repository import PostgreSQLUserFeedRepository

class DatabaseFactory:
    """Factory for creating database repositories"""
    
    def __init__(self):
        self.stage = config.STAGE
        self.environment = config.ENVIRONMENT
        self._dynamo_client = None
        self._opensearch_client = None
        self._postgres_client = None
        self._repositories = {}

    @property
    def dynamo_client(self) -> DynamoDBClient:
        if not self._dynamo_client:
            self._dynamo_client = DynamoDBClient(local=(self.environment == 'LOCAL')).connect()
        return self._dynamo_client

    @property
    def opensearch_client(self) -> OpenSearchClient:
        if not self._opensearch_client:
            self._opensearch_client = OpenSearchClient().connect()
        return self._opensearch_client
        
    @property
    def postgres_client(self) -> PostgreSQLClient:
        if not self._postgres_client:
            self._postgres_client = PostgreSQLClient(local=(self.environment == 'LOCAL')).connect()
        return self._postgres_client

    #########################################################
    #  DynamoDB Repositories
    #########################################################
    def get_user_repository(self) -> DynamoDBUserRepository:
        """Get User repository instance"""
        key = 'user'
        if key not in self._repositories:
            table = self.dynamo_client.get_table(f"user_{self.stage}")
            self._repositories[key] = DynamoDBUserRepository(table)
        return self._repositories[key]

    def get_feed_batch_repository(self) -> DynamoDBFeedBatchRepository:
        """Get feed batch repository instance"""
        key = 'feed_batch'
        if key not in self._repositories:
            table = self.dynamo_client.get_table(f"feed_batch_{self.stage}")
            self._repositories[key] = DynamoDBFeedBatchRepository(table)
        return self._repositories[key]

    def get_generic_repository(self, table_name: str) -> DynamoDBRepository:
        """Get generic repository for simple tables"""
        key = f'generic_{table_name}'
        if key not in self._repositories:
            table = self.dynamo_client.get_table(f"{table_name}_{self.stage}")
            self._repositories[key] = DynamoDBRepository(table)
        return self._repositories[key]
    
    #########################################################
    #  OpenSearch Repositories
    #########################################################
    def get_article_repository(self) -> OpenSearchArticleRepository:
        """Get OpenSearch Article repository instance"""
        key = 'opensearch_article'
        if key not in self._repositories:
            self._repositories[key] = OpenSearchArticleRepository(
                self.opensearch_client.get_client(),
                f"{config.OPENSEARCH_INDEX}_{self.stage}"
            )
        return self._repositories[key]


    #########################################################
    #  PostgreSQL Repositories
    #########################################################
    def get_user_feed_repository(self) -> PostgreSQLUserFeedRepository:
        """Get the PostgreSQL user feed repository"""
        key = 'user_feed'
        if key not in self._repositories:
            self._repositories[key] = PostgreSQLUserFeedRepository(self.postgres_client)
        return self._repositories[key]

# Global factory instance
db_factory = DatabaseFactory()