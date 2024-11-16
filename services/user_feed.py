import datetime

from models.user import User
from db.factory import db_factory
from util import vector_util
from lib.log import logger

class UserFeedService:
    def __init__(self):
        self.user_repo = db_factory.get_user_repository()
        self.listen_history_repo = db_factory.get_generic_repository('user_listen_history')
        self.article_repo = db_factory.get_article_repository()
        self.feed_batch_repo = db_factory.get_feed_batch_repository()

    def _create_feed_entry(self, user, article, is_from_preferred_source):
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
            'score': article.get('score')
        }

    def create_user_feeds_for_articles(self, users, batch_id=None):
        """Create user feeds for a batch of users"""
        try:
            # Get articles that were processed in this batch
            batch = self.feed_batch_repo.get_batch(batch_id) if batch_id else None
            
            articles = self.article_repo.query_by_status(
                'audio_summary_generated',
                start_date=batch.get('start_time') if batch else None
            )
            
            if not articles:
                logger.info("No articles found for feed creation")
                return
            
            for user in users:
                try:
                    # Split articles into preferred and remaining
                    preferred_sources = user.news_sources
                    preferred_articles = [article for article in articles if article.get('domain') in preferred_sources]
                    remaining_articles = [article for article in articles if article.get('domain') not in preferred_sources]

                    # Sort both sets of articles
                    sorted_preferred = self.sort_articles_by_user_preferences(user, preferred_articles)
                    sorted_remaining = self.sort_articles_by_user_preferences(user, remaining_articles)
                    
                    # Create feed entries for all articles
                    user_feed_entries = [
                        self._create_feed_entry(user, article, True)
                        for article in sorted_preferred
                    ] + [
                        self._create_feed_entry(user, article, False)
                        for article in sorted_remaining
                    ]
                    
                    # Bulk create all feed entries for this user
                    user_feed_repo = db_factory.get_user_feed_repository()
                    user_feed_repo.bulk_create(user_feed_entries)
                    
                except Exception as e:
                    logger.error(f"Error creating feed for user {user.id}: {str(e)}")
                    continue
                
        except Exception as e:
            logger.error(f"Error in create_user_feeds_for_articles: {str(e)}")
            raise

    @staticmethod
    def sort_articles_by_user_preferences(user, articles):
        """Sort articles based on user preferences or date published"""
        if user.preferences:
            user_preferences_vector = user.preferences.get("structured_vector") or user.preferences.get("flat_vector")
            if user_preferences_vector:
                return vector_util.sort_by_preference_vector(articles, user_preferences_vector)
        
        return sorted(articles, key=lambda article: article.get('date_published'), reverse=True)

    def get_active_users(self, offset=0, limit=None):
        """
        Get active users (verified and active in the last 7 days) with pagination support.
        Users are sorted by user_id for consistent ordering.
        
        Args:
            offset (int): Number of users to skip
            limit (int): Maximum number of users to return. If None, returns all users
        """
        verified_users = sorted(self.user_repo.get_verified_users(), key=lambda x: x.id)
        seven_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
        
        active_users = []
        for user in verified_users:
            history = self.listen_history_repo.get(user.id)
            if history:
                if history.get('newest_listened_date', '') >= seven_days_ago:
                    active_users.append(user)
            else:
                active_users.append(user)
        
        # Simple array slicing for pagination
        start = offset
        end = offset + limit if limit else None
        return active_users[start:end]