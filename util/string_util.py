from urllib.parse import urlparse
from lib.log import logger
import numpy as np

def generate_request_id():
    return ''.join(np.random.choice(list('0123456789ABCDEF'), size=6))

def extract_domain(url):
    if not url:
        return None
    try:
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'
            
        result = urlparse(url)
        if result.netloc:
            domain = result.netloc.lower()
        else:
            raise ValueError(f"Invalid URL {url}")
        
        if not domain or '.' not in domain:
            return None
            
        return domain.replace('www.', '')
            
    except Exception as e:
        logger.error(f"Invalid URL: {url} - {str(e)}")
        return None


