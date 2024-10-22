# This is done to load the environment variables from the .env file first thing before anyone uses it
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, make_response, Response, stream_with_context
from flask_cors import CORS
from werkzeug.exceptions import BadRequest
from flask import Flask, request, send_file, jsonify
from pydub import AudioSegment
from io import BytesIO
import time
import uuid
import json

import serverless_wsgi
import traceback

from services import summarizer, podcaster, feed_reader, user_news, utilities
from routes.user_routes import user_bp
from routes.test_routes import test_bp
from routes.public_routes import public_bp
from routes.internal_routes import internal_bp
from routes.tracking_routes import tracking_bp

from db import db
from lib.log import logger

from models.audio_story_request import AudioStoryRequest

from flask_jwt_extended import JWTManager

app = Flask(__name__)

# Setup the Flask-JWT-Extended extension
jwt_secret_key = utilities.get_secret("JWT_SECRET_KEY", "your-fallback-secret-key")
app.config["JWT_SECRET_KEY"] = jwt_secret_key
jwt = JWTManager(app)

# Configure CORS to be completely permissive
CORS(app, resources={r"/*": {
    "origins": [
        "https://getessence.app",
        "http://localhost:3000",
        "http://192.168.2.197:3000",
        "https://www.getessence.app",
        "https://main.d1lkh6gn3xrn6w.amplifyapp.com"
    ],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
    "expose_headers": ["Content-Type", "Authorization"]
}})



localMode = True

# Register the user Blueprint
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(test_bp, url_prefix='/test')
app.register_blueprint(public_bp, url_prefix='/public')
app.register_blueprint(internal_bp, url_prefix='/internal')
app.register_blueprint(tracking_bp, url_prefix='/tracking')



@app.route("/")
def home():
    logger.info("Default route")
    return jsonify({"message": "Hi there! Welcome to One click summarizer."})

@app.route('/stream', methods=['POST'])
@stream_with_context
def stream():
    logger.info("stream route")

    body = request.get_json()
    if body is None:
        raise BadRequest("No JSON body received")

    url = body.get("url")
    transcript = body.get("transcript")
    is_test = body.get("test")
    user_id = body.get("user_id")
    instructions = body.get("instructions")  # optional - will use the default if not provided
    include_audio = body.get("audio")  # optional - will assume false if not provided

    # validate the input
    if not url:
        raise BadRequest("URL is required")
    if not transcript:
        raise BadRequest("Transcript is required")
    if len(str(transcript)) < 100:
        raise BadRequest("Transcript is too small")

    # TODO - handle CORS cleanly while building response here
    # Set headers for the response
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"  # Disable buffering for Nginx
    }

    # ID is a hash of the clean url after removing query params
    clean_url = utilities.clean_url(url)
    # TODO P1 - Audio should be generated in the background and be responded in an async way
    # TODO P2 - Stream the response back in a continuous way, using websocket like approach
    # Unique id for the article is generated to cache in the DB. When ID changes, new summary is performed. Hence the importance of Id
    # TODO THINK - Do we want to include instructions and include_audio in the ID ?
    id = utilities.generate_id(url, instructions, include_audio)
    # check if this article exists in the db, and return the object
    item = None
    if is_test is None:
        item = db.get_summary_table().get(id)

        if item and item["text_summary"]:
            logger.info(f"article {id} found in the DB. Returning")
            # Log that this user has requested for this article
            utilities.log_user_activity(user_id, id, clean_url)
            return Response(utilities.build_response(id, item), headers=headers)

    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = utilities.is_worth(id, clean_url)

    if isWorth:
        logger.info(f"Article {id} doesn't exist and its worth. Going to summarize")
        try:
            utilities.log_user_activity(user_id, id, clean_url, "CREATE")
            return Response(summarizer.process_in_stream(user_id, id, clean_url, transcript, instructions, include_audio, item), headers=headers)
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error creating the summary for this article {str(e)}", exc_info=True)
            # Return a not found response if the audio file doesn't exist
            return Response(
                jsonify({"error": "Error creating the summary for this article"}),
                404,
                {"Content-Type": "application/json"},
            )

    else:
        # TODO: On success this API will return an audio file. On failure, we should return a http error response with message
        return Response(
            jsonify({"error": "Sorry.  This content couldn't be summarized. If you think there's something wrong, please submit a ticket to us."}
            ), 404, {"Content-Type": "application/json"},
        )



@app.route('/summarize', methods=['POST'])
def summarize():
    logger.info("summarize route")

    body = request.get_json()
    if body is None:
        raise BadRequest("No JSON body received")

    url = body.get("url")
    transcript = body.get("transcript")
    is_test = body.get("test")
    user_id = body.get("user_id")
    # instructions = body.get("instructions")  # optional - will use the default if not provided
    # include_audio = body.get("audio")  # optional - will assume false if not provided

    # validate the input
    if not url:
        raise BadRequest("URL is required")

    # TODO - handle CORS cleanly while building response here
    # Set headers for the response
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache"
    }

    # Get transcript if not provided in the request
    if not transcript or len(str(transcript)) < 100:
        transcript = utilities.extract_transcript(url)
    
    if len(str(transcript)) < 100:
        raise BadRequest("Transcript could not be extracted. URL might be incorrect")


    # ID is a hash of the clean url after removing query params
    clean_url = utilities.clean_url(url)
    # TODO P1 - Audio should be generated in the background and be responded in an async way
    # TODO P2 - Stream the response back in a continuous way, using websocket like approach
    # Unique id for the article is generated to cache in the DB. When ID changes, new summary is performed. Hence the importance of Id
    # TODO THINK - Do we want to include instructions and include_audio in the ID ?
    id = utilities.generate_id(url)
    # check if this article exists in the db, and return the object
    item = None
    if is_test is None:
        item = db.get_summary_table().get(id)

        if item and item.get("text_summary"):
            logger.info(f"article {id} found in the DB. Returning")
            # Log that this user has requested for this article
            utilities.log_user_activity(user_id, id, clean_url)
            return Response(utilities.build_response(id, item), headers=headers)

    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = utilities.is_worth(id, clean_url)

    if isWorth:
        logger.info(f"Article {id} doesn't exist and its worth. Going to summarize")
        try:
            utilities.log_user_activity(user_id, id, clean_url, "CREATE")
            return Response(summarizer.text_summary(user_id, id, clean_url, transcript, item), headers=headers)
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error creating the summary for this article {str(e)}", exc_info=True)
            # Return a not found response if the audio file doesn't exist
            return Response(
                jsonify({"error": "Error creating the summary for this article"}),
                404,
                {"Content-Type": "application/json"},
            )

    else:
        # TODO: On success this API will return an audio file. On failure, we should return a http error response with message
        return Response(
            jsonify({"error": "Sorry.  This content couldn't be summarized. If you think there's something wrong, please submit a ticket to us."}
            ), 404, {"Content-Type": "application/json"},
        )



@app.route('/inference', methods=['POST'])
def inference():
    logger.info("inference route")

    body = request.get_json()
    if body is None:
        raise BadRequest("No JSON body received")

    url = body.get("url")
    transcript = body.get("transcript")
    is_test = body.get("test")
    user_id = body.get("user_id")
    # instructions = body.get("instructions")  # optional - will use the default if not provided
    include_audio = body.get("audio")  # optional - will assume false if not provided

    # validate the input
    if not url:
        raise BadRequest("URL is required")
    if not transcript:
        raise BadRequest("Transcript is required")
    if len(str(transcript)) < 100:
        raise BadRequest("Transcript is too small")

    # TODO - handle CORS cleanly while building response here
    # Set headers for the response
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache"
    }

    # ID is a hash of the clean url after removing query params
    clean_url = utilities.clean_url(url)
    # TODO P1 - Audio should be generated in the background and be responded in an async way
    # TODO P2 - Stream the response back in a continuous way, using websocket like approach
    # Unique id for the article is generated to cache in the DB. When ID changes, new summary is performed. Hence the importance of Id
    # TODO THINK - Do we want to include instructions and include_audio in the ID ?
    id = utilities.generate_id(url)
    # check if this article exists in the db, and return the object
    item = None
    if is_test is None:
        item = db.get_summary_table().get(id)
        logger.info(f"article {id} found in the DB")

        if item and item.get("audio_summary_url"):
            logger.info(f"article {id} found in the DB. Returning")
            return Response(utilities.build_response(id, item), headers=headers)

    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = utilities.is_worth(id, clean_url)

    if isWorth:
        logger.info(f"Article {id} doesn't exist and its worth. Going to do inference")
        try:
            utilities.log_user_activity(user_id, id, clean_url, "CREATE")
            return Response(summarizer.inference(user_id, id, clean_url, transcript, include_audio, item), headers=headers)
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error creating the inference for this article {str(e)}", exc_info=True)
            # Return a not found response if the audio file doesn't exist
            return Response(
                jsonify({"error": "Error creating the inference for this article"}),
                404,
                {"Content-Type": "application/json"},
            )

    else:
        # TODO: On success this API will return an audio file. On failure, we should return a http error response with message
        return Response(
            jsonify({"error": "Sorry.  This content couldn't be summarized. If you think there's something wrong, please submit a ticket to us."}
            ), 404, {"Content-Type": "application/json"},
        )


# TODO - Flask doesnt support async endpoints - Consider migrating back to FastAPI
# Endpoint for creating an audio snippet of a podcast from a text summary input
@app.route('/audio_story', methods=['POST'])
def audio_story():
    logger.info("audio_story route")

    try:
        start_time = time.time()  # Capture start time

        # Parse the JSON request data into the PodcastRequest object
        data = request.json
        audio_story_request = AudioStoryRequest(**data)

        final_audio = podcaster.generate_audio_story(audio_story_request)

        # Build the streaming response object
        output = BytesIO()
        final_audio.export(output, format="mp3")

        s3_url = utilities.upload_audiostory_to_s3(audio_story_request, output)

        elapsed_time = time.time() - start_time  # Calculate elapsed time
        logger.info(f"audio_story::: Time taken: {elapsed_time:.4f} seconds")

        return jsonify({"id": audio_story_request.id, "s3_url": s3_url})

    except Exception as e:
        logger.error(f"Unhandled error: {str(e)}", exc_info=True)
        return jsonify({"detail": str(e)}), 500

# Endpoint to generate the personalised greeting / intro audio message at the begining of the podcast
@app.route('/intro_audio', methods=['GET'])
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
@app.route('/category_transition_audio', methods=['GET'])
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

# Endpoint to parse all the feeds, extract the transcript, summarize in text and audio and store in the DB
# To be run as a scheduled job few times a day
@app.route('/parse_feeds', methods=['GET'])
def parse_all_feeds():
    return feed_reader.start_feed_processing()

def parse_feeds_scheduled(event, context):
    logger.info("Scheduled parse_feeds job started")
    result = feed_reader.start_feed_processing()
    logger.info(f"Scheduled parse_feeds job completed with result: {result}")
    return {
        'statusCode': 200,
        'body': json.dumps('Scheduled parse_feeds job completed')
    }

def handler(event, context):
    # Check if this is a scheduled event
    if event.get('source') == 'aws.events':
        logger.info("Running scheduled parse_feeds job")
        return parse_feeds_scheduled(event, context)
    
    # TODO - Improve this background task implementation. Maybe it should be in its own package
    if event.get('background_task'):
        # This is a background task
        function_name = event['function_name']
        args = event.get('args', [])
        kwargs = event.get('kwargs', {})

        logger.info(f"Running as a background task: {function_name} with args: {args} and kwargs: {kwargs}")

        # Call the function dynamically from the correct module
        if function_name == 'parse_feeds':
            feed_reader.parse_feeds(*args, **kwargs)
        elif function_name == 'generate_intro_audio_files':
            podcaster.generate_intro_audio_files(*args, **kwargs)
        elif function_name in globals():
            globals()[function_name](*args, **kwargs)
        else:
            logger.error(f"Unknown function: {function_name}")
            return {'statusCode': 400, 'body': json.dumps(f'Unknown function: {function_name}')}
        
        return {'statusCode': 200, 'body': json.dumps('Background task completed')}
    
    logger.info("Running as a normal API Gateway request")
    # Normal API Gateway request
    if "headers" not in event:
        event["headers"] = {}
    
    return serverless_wsgi.handle_request(app, event, context)

