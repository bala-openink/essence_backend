import datetime

from models.user import User
from db.factory import db_factory
from util import vector_util
from lib.log import logger

# Initialize repositories at module level
user_repo = db_factory.get_user_repository()
listen_history_repo = db_factory.get_generic_repository('user_listen_history')
article_repo = db_factory.get_article_repository()
feed_batch_repo = db_factory.get_feed_batch_repository()

def _create_feed_entry(user, article, is_from_preferred_source):
    """Helper method to create a feed entry dictionary"""
    return {
        'user_id': user.id,
        'article_id': article.get('id'),
        'title': article.get('title'),
        'url': article.get('url'),
        'domain': article.get('domain'),
        'image': article.get('image'),
        'date_published': article.get('date_published'),
        'summary_50': article.get('summary_50'),
        'summary_200': article.get('summary_200'),
        'audio_summary': article.get('audio_summary'),
        'categories': article.get('categories'),
        'source_name': article.get('source_name'),
        'type': article.get('type'),
        'is_from_preferred_source': is_from_preferred_source,
        'score': article.get('score', 0),
        'importance_score': article.get('importance_score', 0)
    }

def _create_user_feed(user, articles):
    """Create feed entries for a single user from the given articles"""
    try:
        logger.info(f"Creating feed for user {user.id} with {len(articles)} articles")
        # Split articles into preferred and remaining
        preferred_sources = user.news_sources
        preferred_articles = [article for article in articles if article.get('domain') in preferred_sources]
        remaining_articles = [article for article in articles if article.get('domain') not in preferred_sources]

        # Sort both the set of articles based on user preferences independently
        # And merge them in a way the final list is sorted from least preferred to most preferred
        # ie - Ascending order by score, and remaining articles followed by preferred ones
        # To create a queue where we insert from least preferred to most preferred, and read from most preferred to least preferred
        # This table has an auto-incrementing id to achieve the queue effect
        sorted_preferred = sort_articles_by_user_preferences(user, preferred_articles)
        sorted_remaining = sort_articles_by_user_preferences(user, remaining_articles)
        logger.info(f"Preferred articles: length {len(sorted_preferred)}")
        logger.info(f"Remaining articles: length {len(sorted_remaining)}")
        # Note we add the remaining articles first followed by preferred                    
        user_feed_entries = [
            _create_feed_entry(user, article, False)
            for article in sorted_remaining
        ] + [
            _create_feed_entry(user, article, True)
            for article in sorted_preferred
        ]
        
        # Bulk create all feed entries for this user
        user_feed_repo = db_factory.get_user_feed_repository()
        user_feed_repo.bulk_create(user_feed_entries)
        
    except Exception as e:
        logger.error(f"Error creating feed for user {user.id}: {str(e)}")
        raise

def create_feeds_for_users(users, batch_id=None):
    """Create user feeds for a batch of users"""
    try:
        execution_start_time = datetime.datetime.now(datetime.timezone.utc)
        # Get articles that were processed in this batch
        batch = feed_batch_repo.get_batch(batch_id) if batch_id else None
        
        articles = article_repo.query_by_status(
            'audio_summary_generated',
            start_date=batch.get('start_time') if batch else None,
            limit=1000
        )
        
        if not articles:
            logger.info("No articles found for feed creation")
            return
        
        error_users = []
        for user in users:
            try:
                _create_user_feed(user, articles)
            except Exception as e:
                logger.error(f"Error creating feed for user {user.id}: {str(e)}")
                error_users.append(user.id)
                continue
                
        execution_end_time = datetime.datetime.now(datetime.timezone.utc)
        logger.info(f"create_feeds_for_users::Total execution time for batch {batch_id}, with {len(users)} users for {len(articles)} articles :: {execution_end_time - execution_start_time}")
        
    except Exception as e:
        logger.error(f"Error in create_user_feeds_for_articles: {str(e)}")
        raise

def create_feeds_for_user(user_id):
    """Create feeds for a single user"""
    try:
        if not user_id:
            raise ValueError("User ID is required")
        
        user = user_repo.get(user_id)
        if not user:
            raise ValueError("User not found")
        
        # Get articles that were processed in the last 3 days
        articles = article_repo.query_by_status(
            'audio_summary_generated',
            start_date=(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).isoformat(),
            limit=1000
        )
        
        if not articles:
            logger.info("No articles found for feed creation")
            return

        _create_user_feed(user, articles)
                
    except Exception as e:
        logger.error(f"Error in create_user_feeds_for_articles: {str(e)}")
        raise

@staticmethod
def sort_articles_by_user_preferences(user, articles):
    """Sort articles based on user preferences or date published"""
    if user.preferences:
        user_preferences_vector = user.preferences.get("structured_vector") or user.preferences.get("flat_vector")
        if user_preferences_vector:
            return vector_util.sort_by_preference_vector(articles, user_preferences_vector, descending=False)
    
    return sorted(articles, key=lambda article: article.get('date_published'), reverse=True)

def get_active_users(offset=0, limit=None):
    """
    Get active users (verified and active in the last 7 days) with pagination support.
    Users are sorted by user_id for consistent ordering.
    
    Args:
        offset (int): Number of users to skip
        limit (int): Maximum number of users to return. If None, returns all users
    """
    verified_users = sorted(user_repo.get_verified_users(), key=lambda x: x.id)
    seven_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    
    active_users = []
    for user in verified_users:
        history = listen_history_repo.get(user.id)
        if history:
            if history.get('newest_listened_date', '') >= seven_days_ago:
                active_users.append(user)
        else:
            active_users.append(user)
    
    # Simple array slicing for pagination
    start = offset
    end = offset + limit if limit else None
    return active_users[start:end]