import boto3
import config
from lib.log import logger
from services import utilities

stage = config.STAGE

s3_client = boto3.client(
    's3',
    aws_access_key_id=utilities.get_secret('APP_USER_ACCESS_KEY'),   
    aws_secret_access_key=utilities.get_secret('APP_USER_SECRET_KEY') 
)

def upload_video_to_s3(key: str, video_file) -> str:
    """Upload video file to S3 and return the URL"""
    s3_key = f"{stage}/{key}.mp3"  # Define the S3 object key
    try:
        s3_client.upload_fileobj(
            video_file,
            config.S3_BUCKET_ESSENCE_AUDIO,
            s3_key,
            ExtraArgs={'ContentType': 'video/mp4'}
        )
    except Exception as e:
        logger.error(f"Error uploading video to S3: {str(e)}")
        raise
    # Generate the S3 file URL
    s3_url = f"s3://{config.S3_BUCKET_ESSENCE_AUDIO}/{s3_key}"  
    logger.info(f"Uploaded audio to S3: {s3_url}")
    return s3_url  
