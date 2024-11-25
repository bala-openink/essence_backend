import datetime
from typing import List, Optional, Union
from services import utilities
from lib.log import logger
import time
import numpy as np
from models.user import User
from util import vector_util, date_util
from db.factory import db_factory

user_repository = db_factory.get_user_repository()
user_history_repo = db_factory.get_generic_repository("user_listen_history")
article_repo = db_factory.get_article_repository()
article_repo_old = db_factory.get_article_repository_old()
user_feed_repo = db_factory.get_user_feed_repository()

# To fetch latest news for a user
def get_latest_news(
    user: User, categories: Optional[List[str]] = None, limit: int = 10
) -> List[dict]:
    start_time = time.time()

    # Get the user's history
    user_history = user_history_repo.get(user.id)
    current_newest_date = (
        user_history.get("newest_listened_date") 
        if user_history 
        else (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    )
    current_oldest_date = (
        user_history.get("oldest_listened_date")
        if user_history
        else datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    end_time = time.time()
    logger.debug(f"user_history execution time: {end_time - start_time:.3f} seconds")

    # Get user preferences vector
    user_preferences = user.preferences
    user_preferences_vector = []
    if user_preferences:
        if "structured_vector" in user_preferences:
            user_preferences_vector = user_preferences["structured_vector"]
        elif "flat_vector" in user_preferences:
            user_preferences_vector = user_preferences["flat_vector"]

    # Query new articles (after newest_listened_date)
    new_articles = article_repo_old.query_by_vector(
        user_preferences_vector, start_date=current_newest_date, limit=limit
    )
    logger.debug(f"New articles retrieved: {len(new_articles)}")
    end_time = time.time()
    logger.debug(f"new_articles execution time: {end_time - start_time:.3f} seconds")

    # If we don't have enough new articles, fetch older ones to fill the limit
    if len(new_articles) < limit:
        older_articles = article_repo_old.query_by_vector(
            user_preferences_vector,
            end_date=current_oldest_date,
            limit=limit - len(new_articles),
        )
        logger.debug(f"Older articles retrieved: {len(older_articles)}")
        articles = new_articles + older_articles
    else:
        articles = new_articles

    duplicate_articles, deduplicated_articles = vector_util.deduplicate_articles(articles)

    # Update user's listened dates
    if deduplicated_articles:
        new_new_date = max(
            date_util.parse_iso_date(article.get("date_published")) for article in deduplicated_articles
        )
        new_old_date = min(
            date_util.parse_iso_date(article.get("date_published")) for article in deduplicated_articles
        )

        update_data = {"id": user.id}
        # After every batch of new articles, update the newest_listened_date and oldest_listened_date based on the following
        # The new batch could be fully new - We scraped lot of new news.
        # Or partially new - we scraped a few new news than the batch size
        # Or fully old - No new news have been scraped since the user's last visit.
        if (
            current_newest_date is None
            or date_util.parse_iso_date(current_newest_date) < new_new_date
        ):
            update_data["newest_listened_date"] = (
                new_new_date + datetime.timedelta(seconds=1)
            ).isoformat()
            logger.info(
                f"Updated newest_listened_date to: {new_new_date + datetime.timedelta(seconds=1)}"
            )

        if (
            current_newest_date is not None
            and date_util.parse_iso_date(current_newest_date) < new_old_date
        ):
            update_data["oldest_listened_date"] = (
                new_old_date - datetime.timedelta(seconds=1)
            ).isoformat()
            logger.info(
                f"Updated oldest_listened_date to: {new_old_date - datetime.timedelta(seconds=1)}"
            )

        elif (
            current_oldest_date is None
            or date_util.parse_iso_date(current_oldest_date) > new_old_date
        ):
            update_data["oldest_listened_date"] = (
                new_old_date - datetime.timedelta(seconds=1)
            ).isoformat()
            logger.info(
                f"Updated oldest_listened_date to: {new_old_date - datetime.timedelta(seconds=1)}"
            )

        if len(update_data) > 1:  # More than just 'id'
            user_history_repo.add(update_data)
    else:
        logger.info("No articles found, listened dates remain unchanged")

    end_time = time.time()
    logger.debug(
        f"Total get_latest_news function execution time: {end_time - start_time:.3f} seconds"
    )

    articles = [prepare_for_transport(article) for article in articles]
    return articles

# Convenience method to remove unnecessary fields before responding to client
def prepare_for_transport(article):
    if not article:
        return article
        
    result = dict(article)  # Convert DictRow to regular dict first
    result["audio_summary"] = utilities.generate_audio_url_public(
        result["audio_summary"]
    )
    
    # Remove fields that are not needed for transport
    result.pop("full_text", None)
    result.pop("audio_summary_url", None)
    result.pop("summary_vector", None)
            
    return result

def _fetch_articles_with_retry(
    user_id: str,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    limit: int,
    attempt: int = 1,
    max_attempts: int = 3
) -> List[dict]:
    
    logger.debug(f"Fetching articles with retry for user {user_id} from {start_date} to {end_date} with limit {limit}, attempt {attempt}")
    # Get preferred source articles first
    articles = user_feed_repo.get_latest_news(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        preferred_only=True
    )

    # If we don't have enough articles, get non-preferred source articles
    if len(articles) < limit:
        non_preferred_articles = user_feed_repo.get_latest_news(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit - len(articles),
            preferred_only=False
        )
        articles.extend(non_preferred_articles)

    # If still no articles and we haven't exceeded max attempts, try with an earlier start date
    if not articles and attempt < max_attempts:
        new_start_date = start_date - datetime.timedelta(days=1)
        return _fetch_articles_with_retry(
            user_id=user_id,
            start_date=new_start_date,
            end_date=end_date,
            limit=limit,
            attempt=attempt + 1,
            max_attempts=max_attempts
        )

    return articles

# Update get_latest_news_v2 to use the new method
def get_latest_news_v2(
    user: User, categories: Optional[List[str]] = None, limit: int = 10
) -> List[dict]:
    start_time = time.time()

    start_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    end_date = datetime.datetime.now(datetime.timezone.utc)
    
    articles = _fetch_articles_with_retry(
        user_id=user.id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        max_attempts=5
    )

    if articles:
        # Mark articles as sent
        article_ids = [article["article_id"] for article in articles]
        user_feed_repo.mark_feeds_as_sent(user.id, article_ids)
    else:
        logger.info("No articles found")

    end_time = time.time()
    logger.debug(
        f"Total get_latest_news_v2 function execution time: {end_time - start_time:.3f} seconds"
    )

    return [prepare_for_transport(article) for article in articles]
