import datetime
from threading import Thread
import threading

import os
import hashlib
import time
import json
import concurrent.futures
from urllib.parse import urlparse, urlunparse, quote
from flask import make_response, jsonify, Response
import re
import requests
from bs4 import BeautifulSoup
from io import BytesIO

import boto3
from botocore.exceptions import NoCredentialsError, ClientError

import config
from lib.log import logger
from models.audio_story_request import AudioStoryRequest

stage = config.STAGE

# Utility to retrieve the secrets like credentials, etc from AWS secret manager
def get_secret(secret_key="OPENAI_API_KEY", default_value=None):
    # TODO: Make this dynamic based on the stage
    secret_name = "essence-dev"
    region_name = "us-east-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # Handle any AWS-specific errors
        logger.error(f"Error retrieving secret: {e}")
        return os.environ.get(secret_key, default_value)

    # The secret is stored as a JSON string, so we need to parse it
    if 'SecretString' in get_secret_value_response:
        secret = json.loads(get_secret_value_response['SecretString'])
        return secret.get(secret_key, os.environ.get(secret_key, default_value))
    else:
        # Handle binary secret (if applicable)
        logger.warning("Secret is not a string. Binary secrets are not supported in this implementation.")
        return os.environ.get(secret_key, default_value)

# Initializing s3 client with APP_USER_ACCESS_KEY and APP_USER_SECRET_KEY to give it longer life than the default life the assumed roles have
# NOTE: May not be a good practice. This is to workaround the expiry of public urls that we generate for s3 audio. In long term, we should start using cloudfront
s3_client = boto3.client(
    's3',
    aws_access_key_id=get_secret('APP_USER_ACCESS_KEY'),   
    aws_secret_access_key=get_secret('APP_USER_SECRET_KEY') 
)
lambda_client = boto3.client('lambda')

# Logic to check whether it is worth the effort in summarizing this transcript
#  check if the text is in English and is it a valid article
# TODO implement this later
def is_worth(id, url):
    # If the url is in the list of blacklist, don't proceed
    return not match_regex_list(config.BLACKLIST_URLS, url)


def match_regex_list(regex_list, input_string):
    for pattern in regex_list:
        if re.search(pattern, input_string):
            return True
    return False


# log  activity to DB
def log_user_activity(user_id, article_id, article_url, activity="READ", comments=None):
    # persist the user_activity output
    item = {
        "user_id": user_id or config.DEFAULT_USERNAME,
        "article_id": article_id,
        "article_url": article_url,
        "activity": activity,
        "comments": comments,
        "dateCreated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    bucket_name = config.S3_BUCKET_ACTIVITY_LOGS
    folder_by_day = time.strftime("%Y-%m-%d", time.localtime())  # One folder per day
    s3_key = time.strftime("%Y%m%d%H%M%S%f", time.localtime())[
        :-3
    ]  # current timestamp will the key for the log record
    # Writing to logs in the background, without waiting
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(
            append_logs_to_s3, item, bucket_name, f"{folder_by_day}/{s3_key}"
        )


def append_logs_to_s3(item, bucket_name, key):
    json_data = json.dumps(item)
    # Appending the stage to folder path
    s3_client.put_object(
        Bucket=bucket_name, Key=f"{stage}/{key}", Body=json_data.encode("utf-8")
    )


# File for misc utility methods
def is_non_empty_array(obj):
    return isinstance(obj, list) and len(obj) > 0


# utility to upload to s3. Index is needed only for storing the chunks to remember the insertion order for sorting
def upload_to_s3(file_path, bucket_name, s3_key, index=0):
    try:
        s3_client.upload_file(file_path, bucket_name, f"{stage}/{s3_key}")
        url = f"s3://{bucket_name}/{stage}/{s3_key}"
        print(f"File {file_path} uploaded to {url}")
        return index, url
    except FileNotFoundError:
        print("The file was not found")
    except NoCredentialsError:
        print("Credentials not available")


def download_from_s3(s3_url):
    # Extract bucket name and file key from the S3 URL
    bucket_name = s3_url.split("/")[2]
    file_key = "/".join(s3_url.split("/")[3:])

    # Create a new S3 client

    # Generate a local filename
    local_filename = f"/tmp/{file_key.split('/')[-1]}"

    print(
        f"Downloading the file, {local_filename} from s3 bucket, {bucket_name} and path {file_key}"
    )
    # Download the file from S3
    s3_client.download_file(bucket_name, file_key, local_filename)
    return local_filename


def parse_s3_url(url):
    """
    Parse the S3 URL to get the bucket name and the key
    """
    if url.startswith("s3://"):
        url = url[5:]
    parts = url.split("/", 1)
    bucket_name = parts[0]
    key = parts[1] if len(parts) > 1 else None
    return bucket_name, key


def clean_url(url):
    # Parse the URL
    parsed_url = urlparse(url)
    # Rebuild the URL without query parameters
    return urlunparse(parsed_url._replace(query=""))

def shorten_url(url):
    api_url = "http://tinyurl.com/api-create.php"
    params = {'url': url}
    
    response = requests.get(api_url, params=params)
    
    if response.status_code == 200:
        return response.text
    else:
        return None

def generate_id(url):
    # Hash the clean URL
    key_to_hash = clean_url(url)
    hash_object = hashlib.sha256(key_to_hash.encode())
    # Return the hexadecimal representation of the hash
    return hash_object.hexdigest()


def generate_id(url, instructions="default", include_audio="false"):
    # Hash the clean URL
    key_to_hash = clean_url(url) + instructions + include_audio
    hash_object = hashlib.sha256(key_to_hash.encode())
    # Return the hexadecimal representation of the hash
    return hash_object.hexdigest()


def generate_presigned_url(bucket_name, object_key, expiration=604800):
    """
    Generate a presigned URL for an S3 object.

    Args:
    - bucket_name (str): The name of the S3 bucket.
    - object_key (str): The key of the object within the S3 bucket.
    - expiration (int): Time in seconds for the presigned URL to remain valid.

    Returns:
    - str: A presigned URL to access the S3 object.
    """
    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": object_key},
        ExpiresIn=expiration,
    )
    return presigned_url


def generate_audio_url_public(file_source):
    if file_source:
        if file_source.startswith('s3://'):
            try:
                # Assuming parse_s3_url is defined elsewhere to extract bucket and key
                bucket_name, object_key = parse_s3_url(file_source)
                # logger.info(f"Generating presigned URL for {bucket_name} and {object_key}")
                return generate_presigned_url(bucket_name, object_key)
            except Exception as e:
                print(f"Error generating S3 presigned URL: {e}")
                return None  # Handle error appropriately
        else:
            # Handle local files differently, e.g., by uploading them to S3 first or using a different strategy
            print("Local files need to be handled differently.")
            return None
    else:
        return None





def build_response(id, item):
    if item:
        file_source = item["audio_summary_url"]
        if file_source:
            if file_source.startswith("s3://"):
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
        else:
            audio_url = None

        # Prepare the response as JSON
        response_body = {
            "id": id,
            "audio_url": audio_url,
            **({"tone": item["tone"]} if "tone" in item else {}),
            **({"sentiment": item["sentiment"]} if "sentiment" in item else {}),
            **({"key_topics": item["key_topics"]} if "key_topics" in item else {}),
            **({"text_summary": item["text_summary"]} if "text_summary" in item else {}),
            **({"summary_bullets": item["summary_bullets"]} if "summary_bullets" in item else {}),
            **({"tweet": item["tweet"]} if "tweet" in item else {}),
            **({"time_saved": int(item["time_saved"])} if "time_saved" in item else {}),
            "clean_url": item["url"],
        }

        return json.dumps(response_body)
    else:
        error_response = {"message": "Error, article could not be summarized"}
        return json.dumps(error_response)

def count_words(text):
    # Remove leading/trailing whitespace and split the string into words
    words = text.strip().split()

    # Return the length of the list of words
    return len(words)


def compute_time_saved(transcript, summary):
    transcript_word_count = count_words(transcript) - 250
    summary_word_count = count_words(summary)
    time_transcript = round(transcript_word_count / 150)
    time_summary = round(summary_word_count / 150)
    return time_transcript - time_summary

def upload_audiostory_to_s3(request: AudioStoryRequest, object: BytesIO):
    # Upload the file to S3
    s3_key = f"{stage}/{request.id}/{request.language}-{request.region}-{request.two_speakers}.mp3"  # Define the S3 object key
    try:
        s3_client.upload_fileobj(object, config.S3_BUCKET_ESSENCE_AUDIO, s3_key, ExtraArgs={'ContentType': 'audio/mpeg'})
    except NoCredentialsError:
        logger.error("AWS credentials not available.")
        return jsonify({"detail": "AWS credentials not available."}), 500

    # Generate the S3 file URL
    s3_url = f"s3://{config.S3_BUCKET_ESSENCE_AUDIO}/{s3_key}"  
    logger.info(f"Uploaded audio to S3: {s3_url}")
    return s3_url  

def upload_audio_to_s3(key, object: BytesIO):
    # Upload the file to S3
    s3_key = f"{stage}/{key}.mp3"  # Define the S3 object key
    try:
        s3_client.upload_fileobj(object, config.S3_BUCKET_ESSENCE_AUDIO, s3_key, ExtraArgs={'ContentType': 'audio/mpeg'})
    except NoCredentialsError:
        logger.error("AWS credentials not available.")
        return jsonify({"detail": "AWS credentials not available."}), 500

    # Generate the S3 file URL
    s3_url = f"s3://{config.S3_BUCKET_ESSENCE_AUDIO}/{s3_key}"  
    logger.info(f"Uploaded audio to S3: {s3_url}")
    return s3_url  

def get_time_of_day(current_time):
    try:
        if current_time:
            current_time = datetime.datetime.fromisoformat(current_time)
        if current_time.hour < 12:
            return "morning"
        elif 12 <= current_time.hour < 17:
            return "afternoon"
        else:
            return "evening"
    except Exception as e:
        logger.error(f"Error getting time of day: {e}")
        return "day"

def background_task(task_path, *args, **kwargs):
    if os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
        logger.info("Running a background task inside AWS Lambda")
        payload = {
            'background_task': True,
            'task_path': task_path,
            'args': args,
            'kwargs': kwargs
        }

        lambda_client.invoke(
            FunctionName=os.environ['AWS_LAMBDA_FUNCTION_NAME'],
            InvocationType='Event',
            Payload=json.dumps(payload)
        )
        logger.info(f"Invoked Lambda function for background task: {task_path} with payload: {payload}")
        
    else:
        logger.info("Running a background task locally")
        # Import the function dynamically based on task_path
        module_path, function_name = task_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[function_name])
        func = getattr(module, function_name)
        thread = Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()


# Function to add events and immediately flush to S3
def process_events(events):
    """Process and flush events to S3."""
    if not events:
        logger.info("No events to process.")
        return

    # Convert events to line-delimited JSON (one event per line)
    events_data = '\n'.join(json.dumps(event.to_dict()) for event in events)
    folder_by_day = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    s3_key = f"{stage}/events/{folder_by_day}/{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"

    try:
        s3_client.put_object(
            Bucket=config.S3_BUCKET_ACTIVITY_LOGS,
            Key=s3_key,
            Body=events_data.encode('utf-8'),
            ContentType='application/json'
        )
        logger.info(f"Flushed {len(events)} events to S3: {s3_key}")
    except Exception as e:
        logger.error(f"Failed to flush events to S3: {e}")

# Convenience method to remove unnecessary fields before responding to client
def prepare_for_transport(article):
    if article:
        article["audio_summary"] = generate_audio_url_public(
            article["audio_summary"]
        )
        article["full_text"] = None
        article["audio_summary_url"] = None
        article["summary_vector"] = None
    return article
