import datetime
from typing import List, Optional
from services import utilities
from lib.log import logger
import time
import numpy as np
from models.user import User
from util import vector_util
from db.factory import db_factory

user_repository = db_factory.get_user_repository()
user_history_repo = db_factory.get_generic_repository("user_listen_history")
article_repo = db_factory.get_article_repository()

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
    new_articles = article_repo.query_by_vector(
        user_preferences_vector, start_date=current_newest_date, limit=limit
    )
    logger.debug(f"New articles retrieved: {len(new_articles)}")
    end_time = time.time()
    logger.debug(f"new_articles execution time: {end_time - start_time:.3f} seconds")

    # If we don't have enough new articles, fetch older ones to fill the limit
    if len(new_articles) < limit:
        older_articles = article_repo.query_by_vector(
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
            parse_iso_date(article.get("date_published")) for article in deduplicated_articles
        )
        new_old_date = min(
            parse_iso_date(article.get("date_published")) for article in deduplicated_articles
        )

        update_data = {"id": user.id}
        # After every batch of new articles, update the newest_listened_date and oldest_listened_date based on the following
        # The new batch could be fully new - We scraped lot of new news.
        # Or partially new - we scraped a few new news than the batch size
        # Or fully old - No new news have been scraped since the user's last visit.
        if (
            current_newest_date is None
            or parse_iso_date(current_newest_date) < new_new_date
        ):
            update_data["newest_listened_date"] = (
                new_new_date + datetime.timedelta(seconds=1)
            ).isoformat()
            logger.info(
                f"Updated newest_listened_date to: {new_new_date + datetime.timedelta(seconds=1)}"
            )

        if (
            current_newest_date is not None
            and parse_iso_date(current_newest_date) < new_old_date
        ):
            update_data["oldest_listened_date"] = (
                new_old_date - datetime.timedelta(seconds=1)
            ).isoformat()
            logger.info(
                f"Updated oldest_listened_date to: {new_old_date - datetime.timedelta(seconds=1)}"
            )

        elif (
            current_oldest_date is None
            or parse_iso_date(current_oldest_date) > new_old_date
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


def parse_iso_date(date_string: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(date_string).astimezone(datetime.timezone.utc)


# Convenience method to remove unnecessary fields before responding to client
def prepare_for_transport(article):
    if article:
        article["audio_summary"] = utilities.generate_audio_url_public(
            article["audio_summary"]
        )
        article["full_text"] = None
        article["audio_summary_url"] = None
        article["summary_vector"] = None
    return article
