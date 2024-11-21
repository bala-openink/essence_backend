import boto3
from boto3.dynamodb.conditions import Key

# Use resource instead of client for Table operations
dynamodb = boto3.resource(
    'dynamodb',
    endpoint_url='http://localhost:8000',
    region_name='us-west-2',
    aws_access_key_id='anything',
    aws_secret_access_key='anything'
)

# First list the tables to verify connection
client = boto3.client(
    'dynamodb',
    endpoint_url='http://localhost:8000',
    region_name='us-west-2',
    aws_access_key_id='anything',
    aws_secret_access_key='anything'
)
response = client.list_tables()
print("Tables:", response['TableNames'])

# Get table reference
table_name = 'user_local'
table = dynamodb.Table(table_name)

# Scan will return all items (simpler than query for testing)
try:
    response = table.scan()
    items = response['Items']
    print("Table contents:")
    for item in items:
        print(item)
except Exception as e:
    print(f"Error scanning table: {e}")


print("something".capitalize())