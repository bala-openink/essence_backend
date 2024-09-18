from lib import db
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from services import utilities
from lib.log import logger

# To fetch latest news for a user
def get_latest_news(user_id: str, categories: Optional[List[str]] = None, limit: int = 10) -> List[dict]:
    article_table = db.get_article_table()
    user_history_table = db.get_user_listen_history_table()

    # Get the user's history
    user_history = user_history_table.get(user_id)
    newest_listened_date = user_history.get('newest_listened_date') if user_history else None
    oldest_listened_date = user_history.get('oldest_listened_date') if user_history else None

    # Query new articles (after newest_listened_date)
    new_articles = query_articles(article_table, categories, newest_listened_date, None, limit)
    logger.info(f"New articles retrieved: {len(new_articles)}")

    # If we don't have enough new articles, fetch older ones to fill the limit
    if len(new_articles) < limit:
        older_articles = query_articles(article_table, categories, None, oldest_listened_date, limit - len(new_articles))
        logger.info(f"Older articles retrieved: {len(older_articles)}")
        articles = new_articles + older_articles
    else:
        articles = new_articles

    # Update user's listened dates
    if articles:
        current_new_date = max(parse_iso_date(article['date_published']) for article in articles)
        current_old_date = min(parse_iso_date(article['date_published']) for article in articles)
        
        update_data = {'id': user_id}
        
        if newest_listened_date is None or parse_iso_date(newest_listened_date) < current_new_date:
            update_data['newest_listened_date'] = (current_new_date + timedelta(seconds=1)).isoformat()
            logger.info(f"Updated newest_listened_date to: {current_new_date + timedelta(seconds=1)}")
        
        if oldest_listened_date is None or parse_iso_date(oldest_listened_date) > current_old_date:
            update_data['oldest_listened_date'] = (current_old_date - timedelta(seconds=1)).isoformat()
            logger.info(f"Updated oldest_listened_date to: {current_old_date - timedelta(seconds=1)}")
        
        if len(update_data) > 0:  # More than just 'id'
            user_history_table.addOrUpdate(update_data)
    else:
        logger.info("No articles found, listened dates remain unchanged")

    articles = [prepare_for_transport(article) for article in articles]
    return articles

def parse_iso_date(date_string: str) -> datetime:
    return datetime.fromisoformat(date_string).astimezone(timezone.utc)

def query_articles(article_table, categories, start_date, end_date, limit):
    if start_date:
        start_date = parse_iso_date(start_date).isoformat()
    if end_date:
        end_date = parse_iso_date(end_date).isoformat()
    
    if categories:
        articles = []
        for category in categories:
            category_articles = article_table.query_by_processing_status_date_and_category(
                processing_status='audio_summary_generated',
                category=category,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            articles.extend(category_articles)
        
        # Sort and limit the combined results
        articles.sort(key=lambda x: x['date_published'], reverse=True)
        articles = articles[:limit]
    else:
        articles = article_table.query_by_processing_status_and_date(
            processing_status='audio_summary_generated',
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
    
    return articles

# Convenience method to remove unnecessary fields before responding to client
def prepare_for_transport(article):
    if article:
        article["audio_summary"] = utilities.generate_audio_url_public(article["audio_summary"])
        article["full_text"] = None
        article["audio_summary_url"] = None
    return article
