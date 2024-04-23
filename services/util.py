import hashlib
import time
import json
import concurrent.futures
from urllib.parse import urlparse, urlunparse, quote
from flask import make_response, jsonify

import base64
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

import config
from lib import log

logger = log.setup_logger()


# Logic to check whether it is worth the effort in transcribing and summarizing this video
# Use the popularity, length of the video, etc to decide
# Also check if the video is in English
# TODO implement this later
def is_worth(id):
    return True

# Logic to check whether it is worth the effort in summarizing this transcript
#  check if the text is in English and is it a valid article
# TODO implement this later
def is_worth(id, transcript):
    return True

# log user activity to DB
def log_user_activity(user_id, article_id, article_url, activity = "READ", comments=None):
    # persist the user_activity output
    item = {
        "user_id": user_id or config.DEFAULT_USERNAME,
        "article_id": article_id,
        "article_url": article_url,
        "activity": activity,
        "comments": comments,
        "dateCreated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }
    bucket_name = config.S3_BUCKET_ACTIVITY_LOGS
    folder_by_day = time.strftime("%Y-%m-%d", time.localtime()) # One folder per day
    s3_key = time.strftime("%Y%m%d%H%M%S%f", time.localtime())[:-3] # current timestamp will the key for the log record
    # Writing to logs in the background, without waiting
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(append_logs_to_s3, item, bucket_name, f"{folder_by_day}/{s3_key}")


def append_logs_to_s3(item, bucket_name, key):
    s3 = boto3.client('s3')
    json_data = json.dumps(item)
    s3.put_object(Bucket=bucket_name, Key=key, Body=json_data.encode('utf-8'))


# File for misc utility methods
def is_non_empty_array(obj):
    return isinstance(obj, list) and len(obj) > 0

# utility to upload to s3. Index is needed only for storing the chunks to remember the insertion order for sorting
def upload_to_s3(file_path, bucket_name, s3_key, index = 0):
    try:
        s3_client = boto3.client('s3')
        s3_client.upload_file(file_path, bucket_name, s3_key)
        url = f"s3://{bucket_name}/{s3_key}" 
        print(f"File {file_path} uploaded to {url}")
        return index, url
    except FileNotFoundError:
        print("The file was not found")
    except NoCredentialsError:
        print("Credentials not available")

def download_from_s3(s3_url):
    # Extract bucket name and file key from the S3 URL
    bucket_name = s3_url.split('/')[2]
    file_key = '/'.join(s3_url.split('/')[3:])

    # Create a new S3 client
    s3 = boto3.client('s3')

    # Generate a local filename
    local_filename = f"/tmp/{file_key.split('/')[-1]}"

    print(f"Downloading the file, {local_filename} from s3 bucket, {bucket_name} and path {file_key}")
    # Download the file from S3
    s3.download_file(bucket_name, file_key, local_filename)
    return local_filename

def parse_s3_url(url):
    """
    Parse the S3 URL to get the bucket name and the key
    """
    if url.startswith("s3://"):
        url = url[5:]
    parts = url.split('/', 1)
    bucket_name = parts[0]
    key = parts[1] if len(parts) > 1 else None
    return bucket_name, key


def hash_url(url):
    # Parse the URL
    parsed_url = urlparse(url)
    # Rebuild the URL without query parameters
    clean_url = urlunparse(parsed_url._replace(query="", fragment=""))
    # Hash the clean URL
    hash_object = hashlib.sha256(clean_url.encode())
    # Return the hexadecimal representation of the hash
    return hash_object.hexdigest(), clean_url


def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """
    Generate a presigned URL for an S3 object.

    Args:
    - bucket_name (str): The name of the S3 bucket.
    - object_key (str): The key of the object within the S3 bucket.
    - expiration (int): Time in seconds for the presigned URL to remain valid.

    Returns:
    - str: A presigned URL to access the S3 object.
    """
    s3_client = boto3.client('s3')
    presigned_url = s3_client.generate_presigned_url('get_object',
                                                     Params={'Bucket': bucket_name,
                                                             'Key': object_key},
                                                     ExpiresIn=expiration)
    return presigned_url

def build_response(id, file_source, summary, url):
    if file_source.startswith('s3://'):
        try:
            # Assuming parse_s3_url is defined elsewhere to extract bucket and key
            bucket_name, object_key = parse_s3_url(file_source)
            audio_url = generate_presigned_url(bucket_name, object_key)
        except Exception as e:
            print(f"Error generating S3 presigned URL: {e}")
            return None  # Handle error appropriately
    else:
        # Handle local files differently, e.g., by uploading them to S3 first or using a different strategy
        print("Local files need to be handled differently.")
        return None

    # Prepare the response as JSON
    response_body = {
        "id": id,
        "audio_url": audio_url,
        "summary": summary,
        "clean_url": url
    }

    # TODO - handle CORS cleanly while building response here
    # origin = event['headers'].get('origin', '')
    
    # # Check if the Origin is one of the allowed ones
    # if origin.startswith('chrome-extension://'):
    #     headers = {
    #         'Access-Control-Allow-Origin': origin,
    #         'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    #         # Other CORS headers as needed
    #     }
    # else:
    #     headers = {
    #         'Access-Control-Allow-Origin': 'https://your-allowed-origin.com',
    #         # Other CORS headers as needed
    #     }


    # Set headers for the response
    headers = {
        "Content-Type": "application/json",
    }

    # Return the audio URL and summary in JSON format with the appropriate headers
    response = make_response(jsonify(response_body), 200)
    response.headers.extend(headers)
    return response

# Utility to retrieve the secrets like credentials, etc from AWS secret manager
def get_secret(secret_name = "OPENAI_API_KEY"):
    region_name = "us-west-1"  

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    # Retrieve the secret value
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    # Extract the secret value
    if 'SecretString' in response:
        secret = response['SecretString']
    else:
        # Handle binary secrets
        secret = response['SecretBinary']

    # Return the secret. Secret is stored as a key-value pair.
    # We are using the convention to have the key same as the secret name for simplicity.
    secret_dict = json.loads(secret)
    return secret_dict[secret_name]
