from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.exceptions import BadRequest
from lib.log import logger

from services import user_news, utilities
from db.repo.user_repository import UserRepository

public_bp = Blueprint('public', __name__)
user_repository = UserRepository()

@public_bp.route('/latest_news', methods=['GET'])
@jwt_required()
def latest_news():
    logger.info("latest_news route")

    user_id = get_jwt_identity()
    user = user_repository.get_by_id(user_id)

    if not user:
        return jsonify({"message": "User not found"}), 404

    try:
        categories = request.args.getlist('categories')
        limit = int(request.args.get('limit', 10))

        # Get first_time_ever, first_time_today, current_time from request
        first_time_ever = request.args.get('first_time_ever', 'false').lower() == 'true'
        first_time_today = request.args.get('first_time_today', 'false').lower() == 'true'
        current_time = request.args.get('current_time', None)

        # Based on current_time, identify if its morning, afternoon, evening or night
        time_of_day = utilities.get_time_of_day(current_time)

        #If categories is empty, fetch it from user table
        if not categories:
            categories = user.categories if hasattr(user, 'categories') else None

        # fetch the intro_audio_url from user table, based on first_time_ever, first_time_today, time_of_day
        intro_audios = user.intro_audio_urls if hasattr(user, 'intro_audio_urls') else None
        intro_audio_url = None
        if intro_audios:
            logger.info(f"intro_audios: {intro_audios}")
            key = f"{first_time_ever}_{first_time_today}_{time_of_day}"
            logger.info(f"key: {key}")
            intro_audio_url = intro_audios.get(key, None)

        articles = user_news.get_latest_news(user, categories, limit)

        return jsonify({
            "intro_audio": utilities.generate_audio_url_public(intro_audio_url) if intro_audio_url else None,
            "articles": articles,
            "count": len(articles)
        }), 200

    except Exception as e:
        logger.error(f"Error fetching latest news: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Add more authenticated routes as needed
