import boto3
import pandas as pd
import json
from decimal import Decimal
from pathlib import Path
import numpy as np

stage = 'local' # or 'dev'
# Initialize a DynamoDB resource
if stage == 'local':
    dynamodb = boto3.resource(
                'dynamodb',
                endpoint_url='http://localhost:8000',
                region_name='us-west-2',
                aws_access_key_id='anything',
                aws_secret_access_key='anything'
            )
else:
    dynamodb = boto3.resource('dynamodb')

def batch_write(table, items):
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

def parse_json_fields(item):
    """Convert any JSON string fields to proper dictionaries and handle float values"""
    for key, value in item.items():
        if isinstance(value, str) and value != "NaN":
            try:
                # Try to parse any JSON string fields
                parsed = json.loads(value)
                
                # Handle DynamoDB format conversion
                if isinstance(parsed, dict):
                    # Convert DynamoDB format to plain values
                    new_dict = {}
                    for k, v in parsed.items():
                        if isinstance(v, dict) and "S" in v:
                            new_dict[k] = v["S"]
                        elif isinstance(v, dict) and "L" in v:
                            # Handle lists (vectors)
                            new_dict[k] = [float(x["N"]) if "N" in x else x for x in v["L"]]
                        else:
                            new_dict[k] = v
                    item[key] = new_dict
                
            except json.JSONDecodeError:
                # Not a JSON string, leave as is
                continue
    return item

def convert_floats_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB, handling Infinity and NaN"""
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(v) for v in obj]
    elif isinstance(obj, float):
        if pd.isna(obj):  # Handle NaN
            return None
        if np.isinf(obj):  # Handle Infinity
            return None
        return Decimal(str(obj))
    return obj

def insert_feed_data():
    current_dir = Path(__file__).parent
    file_path = current_dir / 'results.csv'
    
    # Load the CSV file into a pandas DataFrame
    df = pd.read_csv(file_path, dtype={'id': str})
    
    # Convert DataFrame to a list of dictionaries
    data = df.to_dict(orient='records')
    
    # Process each item
    processed_data = []
    for item in data:
        # Parse any JSON string fields
        item = parse_json_fields(item)
        # Convert any float values to Decimal
        item = convert_floats_to_decimal(item)
        processed_data.append(item)
    
    table = dynamodb.Table('feed_' + stage)
    
    try:
        batch_write(table, processed_data)
        print(f"Successfully inserted {len(processed_data)} items into feed_{stage} table.")
    except Exception as e:
        print(f"Error occurred: {e}")

def insert_user_data():
    current_dir = Path(__file__).parent
    file_path = current_dir / 'user_results.csv'
    
    # Load the CSV file into a pandas DataFrame
    df = pd.read_csv(file_path, dtype={'id': str})
    
    # Convert DataFrame to a list of dictionaries
    data = df.to_dict(orient='records')
    
    # Process each item
    processed_data = []
    for item in data:
        # Parse any JSON string fields
        item = parse_json_fields(item)
        # Convert any float values to Decimal
        item = convert_floats_to_decimal(item)
        processed_data.append(item)
    
    table = dynamodb.Table('user_' + stage)
    
    try:
        batch_write(table, processed_data)
        print(f"Successfully inserted {len(processed_data)} items into user_{stage} table.")
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    # You can call either or both functions here
    insert_feed_data()
    insert_user_data()
