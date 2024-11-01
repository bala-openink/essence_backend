from decimal import Decimal
from lib.log import logger
from services import vector_util, llm_util
from db.repo import user_repository


def update_user_preferences(user_id, preferences_text):
    logger.info(f"Updating preferences for user {user_id}")
    try:
        flat_vector = vector_util.create_flat_embedding(preferences_text)
        preferences_json = llm_util.convert_preferences_to_json(preferences_text)
        structured_vector = vector_util.create_user_embedding(preferences_json) if preferences_json else None

        user = user_repository.get_by_id(user_id)
        
        preferences = {
            'text': preferences_text,
        }

        if preferences_json:
            preferences['json'] = preferences_json

        if flat_vector is not None:
            preferences['flat_vector'] = [Decimal(str(x)) for x in flat_vector.tolist()]

        if structured_vector is not None:
            preferences['structured_vector'] = [Decimal(str(x)) for x in structured_vector.tolist()]

        user.preferences = preferences
        user_repository.update(user)
        logger.info(f"Preferences updated successfully for user {user_id}")
    except Exception as e:
        logger.error(f"Error updating preferences for user {user_id}: {str(e)}")
