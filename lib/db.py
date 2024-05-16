from datetime import datetime
import os

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

import config

_SUMMARY_TABLE = None
_USER_TABLE = None
_USER_ACTIVITY_TABLE = None

# Using environment variable to determine local or production deployment
environment = os.getenv('ENVIRONMENT', 'LOCAL')  # Default to 'LOCAL' if not set
# Get the current stage from environment variables
stage = os.environ.get('STAGE', 'dev')
summary_table_name = "content_summary_" + stage
user_table_name = "user_" + stage
user_activity_table_name = "user_activity_" + stage

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
            return None  # The table does not exist, return None.
        else:
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
    print(f"Table {table_name} created successfully.")
    return table  # Return the newly created table object.


# Creates and provide the Singleton instance of the DB impl for Summary table
def get_summary_table():
    global _SUMMARY_TABLE
    if _SUMMARY_TABLE is None:
        dynamodb = create_dynamodb_resource(local=(environment == 'LOCAL'))

        # Try to get the table if it exists
        table = check_table_exists(dynamodb, summary_table_name)

        if table is None:
            print(f"Table {summary_table_name} does not exist. Creating table...")
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
            print(f"Table {user_table_name} does not exist. Creating table...")
            table = create_table(dynamodb, user_table_name)

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
            print(f"Table {user_activity_table_name} does not exist. Creating table...")
            table = create_table(dynamodb, user_activity_table_name)

        _USER_ACTIVITY_TABLE = DynamoDBImpl(table)
    return _USER_ACTIVITY_TABLE


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
            print(f"Exception adding Item to DynamoDB {e}")
        except Exception as e:
            print(f"Exception adding Item to DynamoDB {e}")
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

