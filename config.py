import os

DEFAULT_USERNAME = "default"
S3_BUCKET_AUDIO_OUTPUT = "pp-audio-output"
S3_BUCKET_ACTIVITY_LOGS = "essence-activity-logs"
S3_BUCKET_ESSENCE_AUDIO = "essence-news"
MAX_WAIT_TIME = 300
SLEEP_TIME_IN_SEC = 3
# These are regex patterns that could be used to do selective matches.
# For gmail, the regex pattern will match the inbox, but will not match individual emails
BLACKLIST_URLS = [
    r"google\.com/search",
    r"web.whatsapp\.com",
    r"chatgpt\.com",
    r"youtube\.com/",
    r"linkedin\.com/feed/",
    r"mail\.google\.com/mail/u/0/#inbox(?!/)",
]
# Not sure if this is needed here. No one is using it anyway for now
# JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'your-secret-key')
# JWT_ALGORITHM = 'HS256'
# JWT_EXPIRATION_DELTA = 3600  # 1 hour
# AWS_REGION = os.environ.get('AWS_REGION', 'us-west-1')
# SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'your-verified-email@example.com')
