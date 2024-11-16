from urllib.parse import urlparse
from lib.log import logger

def extract_domain(url):
    if not url:
        return None
    try:
        result = urlparse(url)
        if all([result.scheme, result.netloc]):
            return result.netloc.lower().replace("www.", "")
        else:
            raise ValueError("Invalid URL")
    except ValueError as e:
        logger.error(f"Invalid news source URL: {url} - {str(e)}")
        return None


