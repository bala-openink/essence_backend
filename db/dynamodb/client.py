import boto3
from botocore.exceptions import ClientError
from typing import Optional, Any, Dict

from lib.log import logger
from ..interfaces.database import DatabaseClient
import config

class DynamoDBClient(DatabaseClient):
    """DynamoDB client management"""
    
    def __init__(self, local: bool = False):
        self.local = local
        self._client = None
        self._resource = None
        self._tables = {}  # Cache for table instances
        
    def connect(self) -> 'DynamoDBClient':
        if self.local:
            self._resource = boto3.resource(
                'dynamodb',
                endpoint_url='http://localhost:8000',
                region_name='us-west-2',
                aws_access_key_id='anything',
                aws_secret_access_key='anything'
            )
        else:
            self._resource = boto3.resource('dynamodb')
            
        self._client = self._resource.meta.client
        return self

    def disconnect(self) -> None:
        self._client = None
        self._resource = None
        self._tables = {}

    def is_connected(self) -> bool:
        return self._client is not None

    def get_table(self, table_name: str, create_if_missing: bool = True) -> Optional[Any]:
        """Get or create a table"""
        if table_name in self._tables:
            return self._tables[table_name]

        table = self.check_table_exists(table_name)
        if not table and create_if_missing:
            table = self._create_table(table_name)
        
        if table:
            self._tables[table_name] = table
        return table

    def check_table_exists(self, table_name: str) -> Optional[Any]:
        """Check if table exists"""
        try:
            table = self._resource.Table(table_name)
            table.load()
            return table
        except ClientError as e:
            if e.response['Error']['Code'] == "ResourceNotFoundException":
                logger.error(f"Table {table_name} does not exist")
                return None
            else:
                logger.error(f"Error checking table {table_name} existence: {e}")
                raise

    def _create_table(self, table_name: str) -> Any:
        """Create appropriate table based on name"""
        if "user" in table_name:
            return self.create_user_table(table_name)
        elif "article" in table_name:
            return self.create_article_table(table_name)
        elif "feed" in table_name:
            return self.create_feed_table(table_name)
        elif "article_relevance" in table_name:
            return self.create_article_relevance_table(table_name)
        else:
            return self.create_base_table(table_name)

    def create_base_table(self, table_name: str) -> Any:
        """Create a basic table with id as hash key"""
        table = self._resource.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'id', 'KeyType': 'HASH'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id', 'AttributeType': 'S'},
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        logger.info(f"Table {table_name} created successfully.")
        return table

    def create_user_table(self, table_name: str) -> Any:
        """Create user table with email GSI"""
        table = self._resource.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'id', 'KeyType': 'HASH'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id', 'AttributeType': 'S'},
                {'AttributeName': 'email', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'EmailIndex',
                    'KeySchema': [
                        {'AttributeName': 'email', 'KeyType': 'HASH'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        logger.info(f"Table {table_name} created successfully.")
        return table

    def create_article_table(self, table_name: str) -> Any:
        """Create article table with status and date GSI"""
        table = self._resource.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'id', 'KeyType': 'HASH'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
                {'AttributeName': 'date', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'StatusIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                },
                {
                    'IndexName': 'DateIndex',
                    'KeySchema': [
                        {'AttributeName': 'date', 'KeyType': 'HASH'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        logger.info(f"Table {table_name} created successfully.")
        return table

    def create_feed_table(self, table_name: str) -> Any:
        """Create feed table with status GSI"""
        table = self._resource.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'id', 'KeyType': 'HASH'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'StatusIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        logger.info(f"Table {table_name} created successfully.")
        return table

def create_feed_batch_table(self, table_name: str) -> Any:
    """Create feed batch table"""
    table = self._resource.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'id', 'KeyType': 'HASH'},
        ],
        AttributeDefinitions=[
            {'AttributeName': 'id', 'AttributeType': 'S'},
        ],
        ProvisionedThroughput={
            'ReadCapacityUnits': 10,
            'WriteCapacityUnits': 10
        }
    )
    table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
    logger.info(f"Table {table_name} created successfully.")
    return table