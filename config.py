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
SENDER_EMAIL="hi@getessence.app"
AWS_REGION_FOR_EMAIL = "us-west-1"
OPENSEARCH_HOST = os.environ.get('OPENSEARCH_HOST', 'localhost')
OPENSEARCH_PORT = os.environ.get('OPENSEARCH_PORT', '9200')
OPENSEARCH_INDEX = os.environ.get('OPENSEARCH_INDEX', 'essence-news')

JWT_EXPIRATION_DELTA=604800

SKIP_EXPENSIVE_OPERATIONS = os.environ.get('SKIP_EXPENSIVE_OPERATIONS', 'false').lower() == 'true'
ADMIN_EMAIL = 'balaforfriends@gmail.com'

