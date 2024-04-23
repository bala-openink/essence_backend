import logging, sys

def setup_logger():
    """Set up and return a logger with the given name."""
    logger = logging.getLogger("PP_BACKEND")
    logger.setLevel(logging.INFO)

    # Create a stream handler that outputs to sys.stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    # Create a formatter and set it for the handler
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Add the handler to the logger
    logger.addHandler(handler)

    return logger
