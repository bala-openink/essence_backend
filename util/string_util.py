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


def text_to_dict(text):
    if text and isinstance(text, str):
        try:
            # Remove any leading/trailing whitespace and evaluate the string as a Python literal
            cleaned_text = text.strip()
            if cleaned_text.startswith('{') and cleaned_text.endswith('}'):
                return eval(cleaned_text)
        except Exception as e:
            logger.warning(f"Could not convert text to dict: {str(e)}")
        return None
