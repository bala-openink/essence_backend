import datetime
import dateutil.parser as date_parser
from typing import Union
from lib.log import logger

def format_date_published(date_string):
    if not date_string:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    try:
        # Update date_published to current time if it's too old
        if is_older_than_few_years(date_string):
            return datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Parse the date_string into a datetime object
        parsed_date = date_parser.parse(date_string)
        
        # If the parsed date doesn't have timezone info, assume it's UTC
        if not parsed_date.tzinfo:
            parsed_date = parsed_date.replace(tzinfo=datetime.timezone.utc)
        
        # Convert to UTC if it's not already
        utc_date = parsed_date.astimezone(datetime.timezone.utc)
        
        # Format as ISO 8601 string
        return utc_date.isoformat()
    except ValueError:
        # If parsing fails, use the current UTC time
        logger.warning(f"Failed to parse date: {date_string}. Using current UTC time.")
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

def is_older_than_few_years(date_string, years=10):
    try:
        date = datetime.datetime.fromisoformat(date_string)
        current_date = datetime.datetime.now(datetime.timezone.utc)
        return (current_date - date).days > (years * 365)
    except ValueError:
        logger.error(f"Invalid date format: {date_string}")
        return False

def parse_iso_date(date_value: Union[str, datetime.datetime]) -> datetime.datetime:
    """Convert either a string or datetime to a UTC datetime object"""
    if isinstance(date_value, str):
        return datetime.datetime.fromisoformat(date_value).astimezone(datetime.timezone.utc)
    elif isinstance(date_value, datetime.datetime):
        return date_value.astimezone(datetime.timezone.utc)
    else:
        raise ValueError(f"Unsupported date type: {type(date_value)}")
