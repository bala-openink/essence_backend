from flask import Blueprint, request, jsonify, send_file
from lib.log import logger
import uuid
import datetime

from db.factory import db_factory
from services import utilities
from util import llm_util, feed_util, string_util
from services import feed_processor
from services import podcaster
from models.audio_story_request import AudioStoryRequest
from io import BytesIO
from threading import Thread
from werkzeug.exceptions import BadRequest
import constants

test_bp = Blueprint('test', __name__)


# Define your custom header name and value
CUSTOM_HEADER_NAME = constants.INTERNAL_API_KEY_HEADER
CUSTOM_HEADER_VALUE = utilities.get_secret(secret_key='INTERNAL_API_KEY', default_value="essence-local")

# Apply the custom header check to all routes in the internal blueprint
@test_bp.before_request
def check_custom_header():
    logger.info(f"Checking custom header: {request.headers.get(CUSTOM_HEADER_NAME)} == {CUSTOM_HEADER_VALUE}")
    if request.headers.get(CUSTOM_HEADER_NAME) != CUSTOM_HEADER_VALUE:
        return jsonify({"error": "Unauthorized access"}), 403

article_repo = db_factory.get_article_repository()
user_repo = db_factory.get_user_repository()
feed_batch_repo = db_factory.get_feed_batch_repository()

##################################################################################
# ######## TESTING ENDPOINTS #####################################################
##################################################################################

@test_bp.route('/articles', methods=['GET'])
def test_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"test_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get('limit', default=10, type=int)
        all_attributes = request.args.get('all_attributes', default='false').lower() == 'true'
        attributes_to_show = request.args.get('attributes_to_show', default='audio_summary')
        processing_status = request.args.get('processing_status', default='audio_summary_generated')

        # Query articles from OpenSearch
        items = article_repo.query_by_status(processing_status, limit=limit)

        results = []
        for item in items:
            if all_attributes:
                result = item.copy()
                if 'full_text' in result:
                    # Trim full_text to 50 words
                    result['full_text'] = ' '.join(result['full_text'].split()[:50]) + '...'
                if 'summary_vector' in result:
                    # show first few values of summary_vector
                    result['summary_vector'] = result['summary_vector'][:5]
            elif attributes_to_show:
                # Show only the attributes specified in attributes_to_show
                result = {k: item.get(k) for k in attributes_to_show.split(',')}
            else:
                result = {
                    'id': item.get('id'),
                    'title': item.get('title'),
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

@test_bp.route('/users/<string:user_id>', methods=['DELETE'])
def delete_user(user_id):
    request_id = str(uuid.uuid4())
    logger.info(f"delete_user route - Request ID: {request_id}, User ID: {user_id}")
    try:
        result = user_repo.delete(user_id)

        if result:
            logger.info(f"User deleted successfully - Request ID: {request_id}, User ID: {user_id}")
            return jsonify({'message': f'User with ID {user_id} deleted successfully'}), 200
        else:
            logger.warning(f"User not found or couldn't be deleted - Request ID: {request_id}, User ID: {user_id}")
            return jsonify({'error': f'User with ID {user_id} not found or couldn\'t be deleted'}), 404

    except Exception as e:
        logger.error(f"Error deleting user: {str(e)} - Request ID: {request_id}, User ID: {user_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@test_bp.route('/extract_transcript', methods=['GET'])
def extract_transcript():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    two_speakers = request.args.get('two_speakers', default='true').lower() == 'true'
    model = request.args.get('model', default=constants.DEFAULT_MODEL)

    transcript = feed_util.extract_transcript(url)
    if transcript:
        transcript = transcript.replace('\n', ' ').strip()

    if not transcript:
        return jsonify({'error': 'Failed to extract transcript'}), 500

    article = {
        'id': 'test',
        'url': url,
        'full_text': transcript
    }
    summaries_and_categories = llm_util.summarize_text_and_extract_categories(transcript, model)
    if summaries_and_categories:
        article['summary_50'] = summaries_and_categories.get('summary_50')
        article['summary_200'] = summaries_and_categories.get('summary_200')
        article['categories'] = summaries_and_categories.get('categories')

    audio_request = AudioStoryRequest(
        id=article.get('id'),
        text_summary=article.get('summary_200'),
        url=article.get('url'),
        length="short",
        language="en",
        region="UK",
        two_speakers=two_speakers,
        add_background=False,
        user_name=None
    )
    audio_summary_segment, conversation = podcaster.generate_audio_story(audio_request, model)

    if audio_summary_segment:
        audio_summary = BytesIO()
        audio_summary_segment.export(audio_summary, format="mp3")
        audio_summary.seek(0)

        # Return the audio summary as an mp3 file
        return send_file(audio_summary, mimetype='audio/mpeg', as_attachment=True, download_name='audio_summary.mp3')
    else:
        return jsonify({'error': 'Failed to generate audio summary'}), 500

@test_bp.route('/process_feed', methods=['GET'])
def process_feed():
    logger.info("process_feed route")
    feed_url = request.args.get('feed_url')
    batch_id = string_util.generate_request_id()
    if not feed_url:
        return jsonify({'error': 'feed_url parameter is required'}), 400

    try:
        batch_record = {
            'batch_id': batch_id,
            'total_feeds': 1,
            'start_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        feed_batch_repo.create_batch(batch_record)

        feed = {
            'rss_type': 'rss.app',
            'source_name': 'TEST',
            'category': 'ecommerce',
            'feed_url': feed_url,
            'id': "123456"
        }

        feed_processor.process_stage1(feed, batch_id)
        logger.info(f"Feed reader and audio generation completed for feed_url: {feed_url}")
    except Exception as e:
        logger.error(f"Error in background feed processing: {str(e)}", exc_info=True)
    return jsonify({'message': 'Feed reader and audio generation process started in the background'}), 202

@test_bp.route('/force_process_feed', methods=['GET'])
def force_process_feed():
    logger.info("force_process_feed route")
    force = request.args.get('force', default='false').lower() == 'true'
    try:
        feed_processor.process_stage2(force=force)
        feed_processor.process_stage3()
        logger.info("force_process_feed completed")
    except Exception as e:
        logger.error(f"Error in background feed processing: {str(e)}", exc_info=True)

    return jsonify({'message': 'Feed reader and audio generation process started in the background'}), 202


@test_bp.route('/s3_public_url', methods=['GET'])
def s3_public_url():
    url = request.args.get('url')
    result = utilities.generate_audio_url_public(url)
    return jsonify({'url': result})

# Endpoint to generate the personalised greeting / intro audio message at the begining of the podcast
@test_bp.route('/intro_audio', methods=['GET'])
def intro_audio():
    logger.info("intro_audio route")
    try:
        # Get query parameters with default values
        user_name = request.args.get('user_name', default='there')
        is_first_time_ever = request.args.get('is_first_time_ever', default='false').lower() == 'true'
        is_first_time_today = request.args.get('is_first_time_today', default='false').lower() == 'true'
        time_of_day = request.args.get('time_of_day', default='day')
        two_speakers = request.args.get('two_speakers', default='true').lower() == 'true'

        # Generate intro audio using the updated implementation function
        intro_segment = podcaster.generate_intro_audio(
            userName=user_name,
            isFirstTimeEver=is_first_time_ever,
            isFirstTimeToday=is_first_time_today,
            timeOfDay=time_of_day,
            twoSpeakers=two_speakers
        )

        # Export the audio to a BytesIO object
        intro_audio = BytesIO()
        intro_segment.export(intro_audio, format="mp3")
        intro_audio.seek(0)

        # Return the audio file as a response
        return send_file(
            intro_audio,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name="intro.mp3"
        )

    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        return {"detail": str(e)}, 500


# Endpoint to generate the personalised greeting / intro audio message at the begining of the podcast
@test_bp.route('/category_transition_audio', methods=['GET'])
def category_transition_audio():
    logger.info("category_transition_audio route")
    try:
        # Get query parameters with default values
        category_name = request.args.get('category_name')
        if category_name is None:
            raise BadRequest("No category_name received")

        # Generate category transition audio using the implementation function
        category_transition_segment = podcaster.generate_category_transition_audio(categoryName=category_name)

        # Export the audio to a BytesIO object
        category_transition_audio = BytesIO()
        category_transition_segment.export(category_transition_audio, format="mp3")
        category_transition_audio.seek(0)

        # Return the audio file as a response
        return send_file(
            category_transition_audio,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name="category_transition_audio.mp3"
        )

    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        return {"detail": str(e)}, 500

