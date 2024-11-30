from decimal import Decimal
from lib.log import logger
from util import vector_util, llm_util, string_util
from db.factory import db_factory
from services import user_feed
user_repository = db_factory.get_user_repository()

def update_user_preferences(user_id, preferences_text):
    logger.info(f"Updating preferences for user {user_id}")
    try:
        user = user_repository.get(user_id)
        if not user:
            raise Exception(f"User {user_id} not found")

        flat_vector = vector_util.create_flat_embedding(preferences_text)
        # Try to convert preferences_text to dict if it's a string representation of a dict
        preferences_dict = string_util.text_to_dict(preferences_text)
        # preferences_json = llm_util.convert_preferences_to_json(preferences_dict)
        structured_vector = vector_util.get_user_embedding_with_weights(preferences_dict, user) if preferences_dict else None

        preferences = {
            'text': preferences_text,
        }

        if preferences_dict:
            preferences['json'] = preferences_dict

        if flat_vector is not None:
            preferences['flat_vector'] = [Decimal(str(x)) for x in flat_vector.tolist()]

        if structured_vector is not None:
            preferences['structured_vector'] = [Decimal(str(x)) for x in structured_vector.tolist()]

        user.preferences = preferences
        user_repository.update(user)
        logger.info(f"Preferences updated successfully for user {user_id}")
        # Trigger feed update after preferences are updated
        user_feed.create_feeds_for_user(user.id)        
    except Exception as e:
        logger.error(f"Error updating preferences for user {user_id}: {str(e)}")

