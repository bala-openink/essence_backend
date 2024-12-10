
import requests
import os
from lib.log import logger


def save_image(url, path):
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Validate image was saved successfully
        if not os.path.exists(path):
            raise FileNotFoundError(f"Failed to save image to {path}")
    except Exception as e:
        logger.error(f"Error saving image: {str(e)}", exc_info=True)
        return False
    return True
