from lib import db
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from services import utilities
from lib.log import logger
from boto3.dynamodb.conditions import Key, Attr
import time

# To fetch latest news for a user
def get_latest_news(user_id: str, categories: Optional[List[str]] = None, limit: int = 10) -> List[dict]:
    start_time = time.time()
    
    article_table = db.get_article_table()
    user_history_table = db.get_user_listen_history_table()

    # Get the user's history
    user_history = user_history_table.get(user_id)
    current_newest_date = user_history.get('newest_listened_date') if user_history else None
    current_oldest_date = user_history.get('oldest_listened_date') if user_history else datetime.now(timezone.utc).isoformat()

    # Convert categories to lowercase
    lowercase_categories = [cat.lower() for cat in categories] if categories else None

    logger.debug(f"Categories to fetch: {lowercase_categories}")
    # Query new articles (after newest_listened_date)
    new_articles = query_articles(article_table, lowercase_categories, current_newest_date, None, limit)
    logger.debug(f"New articles retrieved: {len(new_articles)}")

    # If we don't have enough new articles, fetch older ones to fill the limit
    if len(new_articles) < limit:
        older_articles = query_articles(article_table, lowercase_categories, None, current_oldest_date, limit - len(new_articles))
        logger.debug(f"Older articles retrieved: {len(older_articles)}")
        articles = new_articles + older_articles
    else:
        articles = new_articles

    # Update user's listened dates
    if articles:
        new_new_date = max(parse_iso_date(article['date_published']) for article in articles)
        new_old_date = min(parse_iso_date(article['date_published']) for article in articles)
        
        update_data = {'id': user_id}
        # After every batch of new articles, update the newest_listened_date and oldest_listened_date based on the following
        # The new batch could be fully new - We scraped lot of new news.
        # Or partially new - we scraped a few new news than the batch size
        # Or fully old - No new news have been scraped since the user's last visit.
        if current_newest_date is None or parse_iso_date(current_newest_date) < new_new_date:
            update_data['newest_listened_date'] = (new_new_date + timedelta(seconds=1)).isoformat()
            logger.info(f"Updated newest_listened_date to: {new_new_date + timedelta(seconds=1)}")
        
        if(current_newest_date is not None and parse_iso_date(current_newest_date) < new_old_date):
            update_data['oldest_listened_date'] = (new_old_date - timedelta(seconds=1)).isoformat()
            logger.info(f"Updated oldest_listened_date to: {new_old_date - timedelta(seconds=1)}")
        
        elif current_oldest_date is None or parse_iso_date(current_oldest_date) > new_old_date:
            update_data['oldest_listened_date'] = (new_old_date - timedelta(seconds=1)).isoformat()
            logger.info(f"Updated oldest_listened_date to: {new_old_date - timedelta(seconds=1)}")
        
        if len(update_data) > 0:  # More than just 'id'
            user_history_table.addOrUpdate(update_data)
    else:
        logger.info("No articles found, listened dates remain unchanged")

    end_time = time.time()
    logger.debug(f"Total get_latest_news function execution time: {end_time - start_time:.3f} seconds")

    articles = [prepare_for_transport(article) for article in articles]
    return articles

def parse_iso_date(date_string: str) -> datetime:
    return datetime.fromisoformat(date_string).astimezone(timezone.utc)

def query_articles(article_table, categories, start_date, end_date, limit):
    start_time = time.time()
    
    if start_date:
        start_date = parse_iso_date(start_date).isoformat()
    if end_date:
        end_date = parse_iso_date(end_date).isoformat()
    
    key_condition = Key('processing_status').eq('audio_summary_generated')
    if start_date and end_date:
        key_condition &= Key('date_published').between(start_date, end_date)
    elif start_date:
        key_condition &= Key('date_published').gte(start_date)
    elif end_date:
        key_condition &= Key('date_published').lte(end_date)

    query_params = {
        'IndexName': 'ProcessingStatusDateIndex',
        'KeyConditionExpression': key_condition,
        'ScanIndexForward': False,
        'Limit': limit
    }

    if categories:
        # Convert categories to lowercase for case-insensitive matching
        lowercase_categories = [cat.lower() for cat in categories]
        filter_expression = Attr('categories').exists()
        for category in lowercase_categories:
            filter_expression |= Attr('categories').contains(category)
        query_params['FilterExpression'] = filter_expression

    logger.debug(f"Executing DynamoDB query with params: {query_params}")
    query_start_time = time.time()
    articles = article_table.query(**query_params)
    query_end_time = time.time()
    
    items = articles['Items']
    end_time = time.time()
    
    logger.debug(f"DynamoDB query execution time: {query_end_time - query_start_time:.3f} seconds")
    logger.debug(f"Total query_articles function execution time: {end_time - start_time:.3f} seconds")
    logger.debug(f"Number of items retrieved: {len(items)}")
    
    return items

# Convenience method to remove unnecessary fields before responding to client
def prepare_for_transport(article):
    if article:
        article["audio_summary"] = utilities.generate_audio_url_public(article["audio_summary"])
        article["full_text"] = None
        article["audio_summary_url"] = None
    return article
