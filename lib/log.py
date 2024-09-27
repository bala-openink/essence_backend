import logging
import sys
import os

def setup_logger():
    """Set up and return a logger with the given name."""
    logger = logging.getLogger("PP_BACKEND")
    
    # Only set up the logger if it hasn't been set up before
    if not logger.handlers:
        # Set the base level to DEBUG
        logger.setLevel(logging.DEBUG)

        # Create a stream handler that outputs to sys.stdout
        handler = logging.StreamHandler(sys.stdout)
        
        # Determine the default log level based on the environment
        environment = os.getenv('ENVIRONMENT', 'LOCAL')
        default_log_level = 'DEBUG' if environment == 'LOCAL' else 'INFO'
        
        # Set the handler level based on LOG_LEVEL environment variable, 
        # falling back to the default determined by the environment
        log_level = os.environ.get('LOG_LEVEL', default_log_level).upper()
        handler.setLevel(getattr(logging, log_level))

        # Create a formatter and set it for the handler
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        # Add the handler to the logger
        logger.addHandler(handler)

        # Prevent the logger from propagating messages to the root logger
        logger.propagate = False

        logger.info(f"Logger initialized with level: {log_level}")

    return logger

# Create a single instance of the logger
logger = setup_logger()