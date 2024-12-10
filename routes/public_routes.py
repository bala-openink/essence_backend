from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.exceptions import BadRequest
from lib.log import logger
from io import BytesIO
import uuid

from services import user_news, utilities, podcaster
from util import audio_util, llm_util
import tempfile
import os
import time
import base64
from db.factory import db_factory
from routes.decorators import custom_jwt_required

public_bp = Blueprint('public', __name__)
user_repository = db_factory.get_user_repository()
article_repository = db_factory.get_article_repository()

# Unauthenticated routes
@public_bp.route('/article/<public_key>', methods=['GET'])
def get_article(public_key):
    logger.info(f"get_article route: {public_key}")
    if not public_key:
        return jsonify({"message": "Article ID is required"}), 400
    public_key = public_key.strip().lower()
    article = article_repository.get_by_public_key(public_key)
    if not article:
        return jsonify({"message": "Article not found"}), 404
    article = utilities.prepare_for_transport(article)
    return jsonify(article), 200

@public_bp.route('/articles', methods=['GET'])
def articles():
    request_id = str(uuid.uuid4())
    logger.info(f"test_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        date = request.args.get('date', default=None)
        limit = request.args.get('limit', default=20, type=int)
        processing_status = request.args.get('processing_status', default='audio_summary_generated')

        # Set start_date and end_date if date parameter is provided
        start_date = None
        end_date = None
        if date:
            # Set start_date to beginning of day (00:00:00)
            start_date = f"{date}T00:00:00"
            # Set end_date to end of day (23:59:59)
            end_date = f"{date}T23:59:59"

        # Query articles from OpenSearch with date range
        items = article_repository.query_by_status(
            processing_status, 
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )

        results = []
        for item in items:
            result = {
                'id': item.get('id'),
                'title': item.get('title'),
                'summary_50': item.get('summary_50'),
                'summary_200': item.get('summary_200'),
                'source_name': item.get('source_name'),
                'image':item.get('image'),
                'url': item.get('url'),
                'categories': item.get('categories'),
                'processing_status': item.get('processing_status'),
                'date_published': item.get('date_published')
            }
            results.append(result)

        list_size = len(results)
        logger.info(f"Fetched {list_size} articles from OpenSearch - Request ID: {request_id}")
        
        # Include the list size in the response
        response = {
            'count': list_size,
            'articles': [utilities.prepare_for_transport(article) for article in results]
        }
        
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)} - Request ID: {request_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# Authenticated routes
@public_bp.route('/latest_news', methods=['GET'])
@custom_jwt_required()
def latest_news():
    logger.info("latest_news route")

    # Use user_id from kwargs if bypassed
    user_id = getattr(g, 'user_id', None) or get_jwt_identity()
    user = user_repository.get(user_id)

    if not user:
        return jsonify({"message": "User not found"}), 404

    try:
        categories = request.args.getlist('categories')
        limit = int(request.args.get('limit', 20))

        # Get first_time_ever, first_time_today, current_time from request
        first_time_ever = request.args.get('first_time_ever', 'false').lower() == 'true'
        first_time_today = request.args.get('first_time_today', 'false').lower() == 'true'
        current_time = request.args.get('current_time', None)

        # Based on current_time, identify if its morning, afternoon, evening or night
        time_of_day = utilities.get_time_of_day(current_time)

        # fetch the intro_audio_url from user table, based on first_time_ever, first_time_today, time_of_day
        intro_audios = user.intro_audio_urls if hasattr(user, 'intro_audio_urls') else None
        intro_audio_url = None
        if intro_audios:
            logger.info(f"intro_audios: {intro_audios}")
            key = f"{first_time_ever}_{first_time_today}_{time_of_day}"
            logger.info(f"key: {key}")
            intro_audio_url = intro_audios.get(key, None)

        articles = user_news.get_latest_news_v2(user, categories, limit)

        return jsonify({
            "intro_audio": utilities.generate_audio_url_public(intro_audio_url) if intro_audio_url else None,
            "articles": articles,
            "count": len(articles)
        }), 200

    except Exception as e:
        logger.error(f"Error fetching latest news: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@public_bp.route('/process_audio', methods=['POST'])
@jwt_required()
def process_audio():
    start_time = time.time()
    logger.info("Starting process_audio route")

    user_id = get_jwt_identity()
    user = user_repository.get(user_id)

    if not user:
        logger.warning(f"User not found. User ID: {user_id}")
        return jsonify({"message": "User not found"}), 404

    try:
        # Check if the post request has the file part
        if 'audio' not in request.files:
            raise BadRequest("No audio file part in the request")
        
        file = request.files['audio']
        
        if file.filename == '':
            raise BadRequest("No selected file")

        logger.debug("Saving uploaded audio to temporary file")
        temp_save_start = time.time()
        # Create a temporary file to store the uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_audio:
            file.save(temp_audio.name)
            temp_audio_path = temp_audio.name
        logger.debug(f"Temporary file saved. Time taken: {time.time() - temp_save_start:.2f} seconds")

        logger.debug("Starting speech-to-text conversion")
        stt_start = time.time()
        # Use the new speech_to_text function
        with open(temp_audio_path, "rb") as audio_file:
            transcribed_text = audio_util.speech_to_text(audio_file)
        logger.debug(f"Speech-to-text completed. Time taken: {time.time() - stt_start:.2f} seconds")
        logger.debug(f"Transcribed text: {transcribed_text}")
        # Process the transcribed text to understand the user's intent
        intent, action, response_text = llm_util.process_user_intent(transcribed_text)

        # Handle the intent
        if action == "backend":
            success = handle_backend_action(intent, user)
            response_text += " The action has been completed successfully." if success else " Sorry, there was an issue completing the action."
        elif action == "frontend":
            # For frontend actions, we'll include the intent in the response
            pass
        else:
            response_text = "I'm not sure what you want to do. Could you please clarify?"

        logger.debug("Starting text-to-speech conversion")
        tts_start = time.time()
        audio_segment = audio_util.text_to_speech(response_text, "male")
        logger.debug(f"Text-to-speech completed. Time taken: {time.time() - tts_start:.2f} seconds")

        # Convert audio to base64
        buffer = BytesIO()
        audio_segment.export(buffer, format="mp3")
        audio_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        total_time = time.time() - start_time
        logger.info(f"process_audio completed. Total time taken: {total_time:.2f} seconds")

        # Prepare the response with both JSON data and base64 encoded audio
        response = jsonify({
            "text_response": response_text,
            "intent": intent,
            "action": action,
            "audio_data": audio_base64
        })

        return response, 200

    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Error processing audio: {str(e)}. Total time taken: {total_time:.2f} seconds", exc_info=True)
        return jsonify({'error': str(e)}), 500

    finally:
        # Clean up the input temporary file
        if 'temp_audio_path' in locals():
            os.unlink(temp_audio_path)

def handle_backend_action(intent, user):
    # Implement backend actions here
    if intent == "bookmark":
        # Implement bookmarking logic
        return True
    # Add more backend actions as needed
    return False

# Add more authenticated routes as needed
