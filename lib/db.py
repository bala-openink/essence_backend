from datetime import datetime
import os

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from boto3.dynamodb.conditions import Key, Attr
from lib.log import logger

import config

_SUMMARY_TABLE = None
_USER_TABLE = None
_USER_ACTIVITY_TABLE = None
_ARTICLE_TABLE = None
_USER_LISTEN_HISTORY_TABLE = None
_FEED_TABLE = None

# Using environment variable to determine local or production deployment
# environment = os.getenv('ENVIRONMENT', 'LOCAL')  # Default to 'LOCAL' if not set
environment = 'PRODUCTION'
# Get the current stage from environment variables
stage = os.environ.get('STAGE', 'dev')
summary_table_name = "content_summary_" + stage
user_table_name = "user_" + stage
user_activity_table_name = "user_activity_" + stage
article_table_name = "article_" + stage
user_listen_history_table_name = "user_listen_history_" + stage
feed_table_name = "feed_" + stage

def create_dynamodb_resource(local=False):
    if local:
        return boto3.resource('dynamodb', 
                              endpoint_url='http://localhost:8000',
                              region_name='us-west-2',
                              aws_access_key_id='anything',  # DynamoDB Local doesn't care about these values
                              aws_secret_access_key='anything')
    else:
        return boto3.resource('dynamodb')


def check_table_exists(dynamodb, table_name):
    try:
        table = dynamodb.Table(table_name)
        table.load()  # This call attempts to load table details, raising ResourceNotFoundException if the table doesn't exist.
        return table  # The table exists, return the table object.
    except ClientError as e:
        if e.response['Error']['Code'] == "ResourceNotFoundException":
            logger.error(f"Table {table_name} does not exist")
            return None  # The table does not exist, return None.
        else:
            logger.error(f"Error checking table {table_name} existence: {e}")
            raise


def create_table(dynamodb, table_name):
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'id', 'KeyType': 'HASH'},  # Partition key
        ],
        AttributeDefinitions=[
            {'AttributeName': 'id', 'AttributeType': 'S'},
        ],
        ProvisionedThroughput={'ReadCapacityUnits': 10, 'WriteCapacityUnits': 10}
    )
    # Wait until the table exists.
    table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
    logger.info(f"Table {table_name} created successfully.")
    return table  # Return the newly created table object.

def create_user_table(dynamodb, table_name):
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'id', 'KeyType': 'HASH'},  # Partition key
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
        ProvisionedThroughput={'ReadCapacityUnits': 10, 'WriteCapacityUnits': 10}
    )
    table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
    logger.info(f"Table {table_name} created successfully.")
    return table

# Creates and provide the Singleton instance of the DB impl for ARTICLE table, 
# with a GSI on processing_status and date_published
def create_article_table(dynamodb, table_name):
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'id', 'KeyType': 'HASH'},  # Partition key
        ],
        AttributeDefinitions=[
            {'AttributeName': 'id', 'AttributeType': 'S'},
            {'AttributeName': 'processing_status', 'AttributeType': 'S'},
            {'AttributeName': 'date_published', 'AttributeType': 'S'}
        ],
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'ProcessingStatusDateIndex',
                'KeySchema': [
                    {'AttributeName': 'processing_status', 'KeyType': 'HASH'},
                    {'AttributeName': 'date_published', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'},
                'ProvisionedThroughput': {
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            }
        ],
        ProvisionedThroughput={'ReadCapacityUnits': 10, 'WriteCapacityUnits': 10}
    )
    table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
    logger.info(f"Table {table_name} created successfully.")
    return table

# Creates and provide the Singleton instance of the DB impl for Summary table
def get_summary_table():
    global _SUMMARY_TABLE
    if _SUMMARY_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, summary_table_name)

        if table is None:
            logger.info(f"Table {summary_table_name} does not exist. Creating table...")
            table = create_table(dynamodb, summary_table_name)

        _SUMMARY_TABLE = DynamoDBImpl(table)
    return _SUMMARY_TABLE


# Creates and provide the Singleton instance of the DB impl for User table
def get_user_table():
    global _USER_TABLE
    if _USER_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, user_table_name)

        if table is None:
            logger.info(f"Table {user_table_name} does not exist. Creating table...")
            table = create_user_table(dynamodb, user_table_name)

        _USER_TABLE = DynamoDBImpl(table)
    return _USER_TABLE

# Creates and provide the Singleton instance of the DB impl for USER_ACTIVITY table
# NOTE - Not using this now - writing to s3 directly.
def get_user_activity_table():
    global _USER_ACTIVITY_TABLE
    if _USER_ACTIVITY_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, user_activity_table_name)

        if table is None:
            logger.info(f"Table {user_activity_table_name} does not exist. Creating table...")
            table = create_table(dynamodb, user_activity_table_name)

        _USER_ACTIVITY_TABLE = DynamoDBImpl(table)
    return _USER_ACTIVITY_TABLE

# Creates and provide the Singleton instance of the DB impl for ARTICLE table
def get_article_table():
    global _ARTICLE_TABLE
    if _ARTICLE_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, article_table_name)    

        if table is None:
            logger.info(f"Table {article_table_name} does not exist. Creating table...")
            table = create_article_table(dynamodb, article_table_name)

        _ARTICLE_TABLE = DynamoDBImpl(table)
    return _ARTICLE_TABLE

# Creates and provide the Singleton instance of the DB impl for USER_LISTEN_HISTORY table
def get_user_listen_history_table():
    global _USER_LISTEN_HISTORY_TABLE
    if _USER_LISTEN_HISTORY_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, user_listen_history_table_name)

        if table is None:
            logger.info(f"Table {user_listen_history_table_name} does not exist. Creating table...")
            table = create_table(dynamodb, user_listen_history_table_name)

        _USER_LISTEN_HISTORY_TABLE = DynamoDBImpl(table)
    return _USER_LISTEN_HISTORY_TABLE

# Creates and provide the Singleton instance of the DB impl for FEED table
def create_feed_table(dynamodb, table_name):
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {'AttributeName': 'id', 'KeyType': 'HASH'},  # Partition key
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
        ProvisionedThroughput={'ReadCapacityUnits': 10, 'WriteCapacityUnits': 10}
    )
    table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
    logger.info(f"Table {table_name} created successfully.")
    return table

def get_feed_table():
    global _FEED_TABLE
    if _FEED_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, feed_table_name)

        if table is None:
            logger.info(f"Table {feed_table_name} does not exist. Creating table...")
            table = create_feed_table(dynamodb, feed_table_name)

        _FEED_TABLE = DynamoDBImpl(table)
    return _FEED_TABLE

# DB interface
class DB(object):
    def list(self):
        pass

    def add(self, item):
        pass

    def get(self, id):
        pass

    def delete(self, id):
        pass

# DynamoDB implementation of the DB Interface
class DynamoDBImpl(DB):
    def __init__(self, table_resource):
        self._table = table_resource

    def list(self):
        response = self._table.scan()
        return response['Items']

    def add(self, item):
        try:
            if item:
                self._table.put_item(Item=item)
                return item
            else:
                raise ValueError('Item empty')
        except ClientError as e:
            logger.error(f"Exception adding Item to DynamoDB {e}")
        except Exception as e:
            logger.error(f"Exception adding Item to DynamoDB {e}")
        return None
        
    # Returns the item if found. Returns None if not found
    def get(self, id):
        response = self._table.get_item(
            Key={
                'id': id
            }
        )
        if 'Item' in response:
            return response['Item']
        else:
            return None

    # Query the table with the provided kwargs
    def query(self, **kwargs):
        try:
            response = self._table.query(**kwargs)
            return response
        except ClientError as e:
            logger.error(f"Error querying DynamoDB: {e}")
            raise

    # Returns True if succesfully deleted. Returns False on error 
    def delete(self, id):
        try:
            self._table.delete_item(
                Key={
                    'id': id
                }
            )
            return True
        except ClientError as e:
            return False
                
    # Updates an item if the key exists. If the key doesn't exist, it adds the item.
    # Returns the updated/added item if successful, None otherwise.
    def addOrUpdate(self, item):
        try:
            id = item['id']
            existing_item = self.get(id)
            if existing_item:
                # Merge the new item with the existing item
                existing_item.update(item)
                self._table.put_item(Item=existing_item)
                return existing_item
            else:
                # Add the new item
                self._table.put_item(Item=item)
                return item
        except ClientError as e:
            print(f"Exception updating/adding Item in DynamoDB {e}")
            return None
        except Exception as e:
            print(f"Exception updating/adding Item in DynamoDB {e}")
            return None

    def query_by_processing_status_and_date(self, processing_status, start_date=None, end_date=None, limit=10):
        key_condition = Key('processing_status').eq(processing_status)
        if start_date and end_date:
            key_condition &= Key('date_published').between(start_date, end_date)
        elif start_date:
            key_condition &= Key('date_published').gte(start_date)
        elif end_date:
            key_condition &= Key('date_published').lte(end_date)

        response = self._table.query(
            IndexName='ProcessingStatusDateIndex',
            KeyConditionExpression=key_condition,
            ScanIndexForward=False,  # This will sort in descending order (newest first)
            Limit=limit
        )
        return response['Items']

    def query_by_processing_status_date_and_category(self, processing_status, category=None, start_date=None, end_date=None, limit=10):
        key_condition = Key('processing_status').eq(processing_status)
        if start_date and end_date:
            key_condition &= Key('date_published').between(start_date, end_date)
        elif start_date:
            key_condition &= Key('date_published').gt(start_date)
        elif end_date:
            key_condition &= Key('date_published').lt(end_date)

        query_params = {
            'IndexName': 'ProcessingStatusDateIndex',
            'KeyConditionExpression': key_condition,
            'ScanIndexForward': False,  # This will sort in descending order (newest first)
            'Limit': limit
        }

        if category:
            query_params['FilterExpression'] = Attr('categories').contains(category)

        response = self._table.query(**query_params)
        return response['Items']

    def get_user_by_email(self, email):
        response = self._table.query(
            IndexName='EmailIndex',
            KeyConditionExpression=Key('email').eq(email)
        )
        items = response.get('Items', [])
        return items[0] if items else None

    def query_articles(self, limit=None, processing_status='audio_summary_generated'):
        query_params = {
            'IndexName': 'ProcessingStatusDateIndex',
            'KeyConditionExpression': Key('processing_status').eq(processing_status),
            'ScanIndexForward': False,  # This will sort in descending order (newest first)
        }

        if limit is not None:
            query_params['Limit'] = limit

        response = self._table.query(**query_params)
        return response['Items']

    def query_enabled_feeds(self):
        response = self._table.query(
            IndexName='StatusIndex',
            KeyConditionExpression=Key('status').eq('enabled')
        )
        return response['Items']

    def update_last_processed_date(self, feed_id, last_processed_date):
        self._table.update_item(
            Key={'id': feed_id},
            UpdateExpression='SET last_processed_date = :date',
            ExpressionAttributeValues={':date': last_processed_date}
        )


