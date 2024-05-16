import boto3

# Initialize DynamoDB client
dynamodb = boto3.client('dynamodb')

# Define table name
table_name = 'YourTableName'

# Define attribute definitions for indexes
attribute_definitions = [
    {'AttributeName': 'userid', 'AttributeType': 'S'},  # Assuming userid is a string attribute
    {'AttributeName': 'date', 'AttributeType': 'S'}     # Assuming date is a string attribute
]

# Define global secondary index for userid
global_secondary_indexes = [
    {
        'IndexName': 'userid-index',
        'KeySchema': [{'AttributeName': 'userid', 'KeyType': 'HASH'}],
        'Projection': {'ProjectionType': 'ALL'}
    }
]

# Define local secondary index for userid and date
local_secondary_indexes = [
    {
        'IndexName': 'userid-date-index',
        'KeySchema': [
            {'AttributeName': 'itemid', 'KeyType': 'HASH'},  # Partition key same as base table's partition key
            {'AttributeName': 'date', 'KeyType': 'RANGE'}    # Sort key
        ],
        'Projection': {'ProjectionType': 'ALL'}
    }
]

# Create the DynamoDB table with indexes
response = dynamodb.create_table(
    TableName=table_name,
    KeySchema=[
        {'AttributeName': 'itemid', 'KeyType': 'HASH'}  # Assuming itemid is the primary key
    ],
    AttributeDefinitions=attribute_definitions,
    GlobalSecondaryIndexes=global_secondary_indexes,
    LocalSecondaryIndexes=local_secondary_indexes,
    ProvisionedThroughput={
        'ReadCapacityUnits': 5,
        'WriteCapacityUnits': 5
    }
)

# Wait for the table to be created
table_waiter = dynamodb.get_waiter('table_exists')
table_waiter.wait(TableName=table_name)

print("Table created successfully with indexes:", response)
