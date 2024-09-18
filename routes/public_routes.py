from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest, Unauthorized
from lib.log import logger
from lib import db
import uuid
from functools import wraps

from services import user_news, utilities
from lib.auth import verify_token

public_bp = Blueprint('public', __name__)

def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            raise Unauthorized("Missing Authorization header")

        token = auth_header.split(' ')[1]
        user_id = verify_token(token)

        if not user_id:
            raise Unauthorized("Invalid or expired token")

        user_table = db.get_user_table()
        user = user_table.get(user_id)

        if not user:
            raise Unauthorized("User not found")

        return f(user, *args, **kwargs)
    return decorated_function

@public_bp.route('/latest_news', methods=['GET'])
@jwt_required
def latest_news(user):
    logger.info("latest_news route")
    try:
        categories = request.args.getlist('category')
        limit = int(request.args.get('limit', 10))

        # Get first_time_ever, first_time_today, current_time from request
        first_time_ever = request.args.get('first_time_ever', False)
        first_time_today = request.args.get('first_time_today', False)
        current_time = request.args.get('current_time', None)

        # Based on current_time, identify if its morning, afternoon, evening or night
        time_of_day = utilities.get_time_of_day(current_time)

        # fetch the intro_audio_url from user table, based on first_time_ever, first_time_today, time_of_day
        intro_audios = user.get('intro_audio_urls', None)
        key = f"{first_time_ever}_{first_time_today}_{time_of_day}"
        intro_audio_url = intro_audios.get(key, None)


        articles = user_news.get_latest_news(user['id'], categories, limit)

        return jsonify({
            "intro_audio": utilities.generate_audio_url_public(intro_audio_url),
            "articles": articles,
            "count": len(articles)
        }), 200

    except Exception as e:
        logger.error(f"Error fetching latest news: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Add more authenticated routes as needed

