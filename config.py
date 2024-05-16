DEFAULT_USERNAME = "default"
S3_BUCKET_AUDIO_OUTPUT = "pp-audio-output"
S3_BUCKET_ACTIVITY_LOGS = "essence-activity-logs"
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
