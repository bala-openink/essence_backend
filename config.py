import os


ENVIRONMENT = os.getenv('ENVIRONMENT', 'local')  # Default to 'LOCAL' if not set
STAGE = os.getenv('STAGE', 'local')

JWT_EXPIRATION_DELTA=604800

SKIP_EXPENSIVE_OPERATIONS = os.environ.get('SKIP_EXPENSIVE_OPERATIONS', 'false').lower() == 'true'
SKIP_SUMMARY_CREATION = os.environ.get('SKIP_SUMMARY_CREATION', 'false').lower() == 'true'
SKIP_AUDIO_GENERATION = os.environ.get('SKIP_AUDIO_GENERATION', 'false').lower() == 'true'

ADMIN_EMAIL = 'balaforfriends@gmail.com'

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
OPENSEARCH_USERNAME = os.environ.get('OPENSEARCH_USERNAME', 'admin')
OPENSEARCH_PASSWORD = os.environ.get('OPENSEARCH_PASSWORD', 'admin')

# PostgreSQL Configuration
PG_HOST = os.environ.get('PG_HOST', 'localhost')
PG_PORT = os.environ.get('PG_PORT', '5432')
PG_DATABASE = os.environ.get('PG_DATABASE', 'essence')
PG_USER = os.environ.get('PG_USER', 'bala')
PG_PASSWORD = os.environ.get('PG_PASSWORD', 'bala')

RETAIL_FUNCTIONS = [
    "Sales",
    "Marketing",
    "Merchandising",
    "Inventory Management",
    "Supply Chain & Logistics", 
    "Customer Service",
    "Finance",
    "Human Resources",
    "IT & Technology",
    "Security"
]

RETAIL_INDUSTRIES = [
    "Grocery",
    "Fashion",
    "Electronics",
    "Home Furnishings",
    "Beauty",
    "Health & Wellness",
    "Automotive",
    "Sports & Outdoors",   
    "Toys & Hobbies",
    "Office Supplies",
    "Books, Music & Entertainment",
    "Jewelry & Accessories",
    "Pet Supplies",
    "DIY & Hardware",
    "Luxury Goods"  
]