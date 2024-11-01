from flask import Blueprint, request, jsonify, send_file
from lib.log import logger
from db import db
import uuid
from services import utilities
from util import llm_util
from services import feed_reader
from services import podcaster
from models.audio_story_request import AudioStoryRequest
from io import BytesIO
from threading import Thread

test_bp = Blueprint('test', __name__)

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
        processing_status = request.args.get('processing_status', default='audio_summary_generated')

        # Query articles from OpenSearch
        items = db.query_articles_by_status(processing_status, limit=limit)

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
            'articles': results
        }
        
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)} - Request ID: {request_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@test_bp.route('/users', methods=['GET'])
def test_users():
    request_id = str(uuid.uuid4())
    logger.info(f"test_users route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get('limit', default=None, type=int)
        all_attributes = request.args.get('all_attributes', default='false').lower() == 'true'

        table = db.get_user_table()
        items = table.list() # TODO list only a fixed number of users, instead of all users

        # Extract desired fields
        results = []
        for item in items:
            result = item.copy()
            
            if all_attributes:
                if 'password_hash' in result:
                    del result['password_hash']  # Remove sensitive information
            else:
                if 'intro_audio_urls' in result:
                    del result['intro_audio_urls'] 
                if 'preferences' in result:
                    del result['preferences']

            results.append(result)

        # Apply limit if specified
        if limit is not None:
            results = results[:limit]

        list_size = len(results)
        logger.info(f"Fetched {list_size} users from DynamoDB - Request ID: {request_id}")
        
        # Include the list size in the response
        response = {
            'count': list_size,
            'users': results
        }
        
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error fetching users: {str(e)} - Request ID: {request_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@test_bp.route('/users/<string:user_id>', methods=['DELETE'])
def delete_user(user_id):
    request_id = str(uuid.uuid4())
    logger.info(f"delete_user route - Request ID: {request_id}, User ID: {user_id}")
    try:
        table = db.get_user_table()
        result = table.delete(user_id)

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

    transcript = utilities.extract_transcript(url)
    transcript = transcript.replace('\n', ' ').strip()
    logger.debug(f"Transcript: {transcript}")

    if not transcript:
        return jsonify({'error': 'Failed to extract transcript'}), 500

    article = {
        'id': 'test',
        'url': url,
        'full_text': transcript
    }
    summaries_and_categories = llm_util.summarize_text_and_extract_categories(transcript)
    article['summary_50'] = summaries_and_categories.get('summary_50')
    article['summary_200'] = summaries_and_categories.get('summary_200')
    article['categories'] = summaries_and_categories.get('categories')

    audio_request = AudioStoryRequest(
        id=article['id'],
        text_summary=article['summary_200'],
        url=article['url'],
        length="short",
        language="en",
        region="UK",
        two_speakers=False,
        add_background=False,
        user_name=None
    )
    audio_summary_segment = podcaster.generate_audio_story(audio_request)

    audio_summary = BytesIO()
    audio_summary_segment.export(audio_summary, format="mp3")
    audio_summary.seek(0)

    # Return the audio summary as an mp3 file
    return send_file(audio_summary, mimetype='audio/mpeg', as_attachment=True, download_name='audio_summary.mp3')

@test_bp.route('/feed_reader', methods=['GET'])
def test_feed_reader():
    feed_url = request.args.get('feed_url')
    if not feed_url:
        return jsonify({'error': 'feed_url parameter is required'}), 400

    def background_process():
        try:
            feed_reader.parse_rss_app_feed("TEST", "ecommerce", feed_url)
            feed_reader.process_summaries_and_generate_audio()
            logger.info(f"Feed reader and audio generation completed for feed_url: {feed_url}")
        except Exception as e:
            logger.error(f"Error in background feed processing: {str(e)}", exc_info=True)

    # Start the background thread
    Thread(target=background_process).start()

    return jsonify({'message': 'Feed reader and audio generation process started in the background'}), 202
