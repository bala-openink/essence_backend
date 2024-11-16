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

from lib.log import logger
from db.factory import db_factory

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
        "https://main.d1lkh6gn3xrn6w.amplifyapp.com",
        "https://dev.d1vn9ca3svg0a2.amplifyapp.com"
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

summary_repo = db_factory.get_generic_repository("content_summary")

@app.route("/")
def home():
    logger.info("Default route")
    return jsonify({"message": "Hi there! Welcome to Essence."})


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
        item = summary_repo.get(id)
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
            return jsonify({"error": "Error creating the inference for this article"}), 404

    else:
        # TODO: On success this API will return an audio file. On failure, we should return a http error response with message
        return jsonify({
            "error": "Sorry. This content couldn't be summarized. If you think there's something wrong, please submit a ticket to us."
        }), 404, {"Content-Type": "application/json"}


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


# Endpoint to parse all the feeds, extract the transcript, summarize in text and audio and store in the DB
# To be run as a scheduled job few times a day
@app.route('/parse_feeds', methods=['GET'])
def parse_all_feeds():
    return feed_reader.parse_feeds()

def parse_feeds_scheduled(event, context):
    logger.info("Scheduled parse_feeds job started")
    result = feed_reader.parse_feeds()
    logger.info(f"Scheduled parse_feeds job completed with result: {result}")
    return {
        'statusCode': 200,
        'body': json.dumps('Scheduled parse_feeds job completed')
    }

def execute_background_task(task_path, args=None, kwargs=None):
    """
    Dynamically execute a background task, supporting both functions and class methods
    """
    args = args or []
    kwargs = kwargs or {}
    
    try:
        # Split the path into parts
        *module_parts, final_part = task_path.split('.')
        module_path = '.'.join(module_parts)
        
        # Import the module
        module = __import__(module_path, fromlist=[final_part])
        
        # Get the target (could be function, class, or class method)
        target = module
        for part in module_path.split('.')[1:]:
            target = getattr(target, part)
            
        # If the final part contains a class and method
        if '.' in final_part:
            class_name, method_name = final_part.split('.')
            class_obj = getattr(target, class_name)
            
            # If it's a static method or class method
            if hasattr(class_obj, method_name):
                task_function = getattr(class_obj, method_name)
            else:
                # If it's an instance method, create an instance
                instance = class_obj()
                task_function = getattr(instance, method_name)
        else:
            # Regular function
            task_function = getattr(target, final_part)
            
        return task_function(*args, **kwargs)
        
    except Exception as e:
        logger.error(f"Error executing background task {task_path}: {str(e)}", exc_info=True)
        raise

def handler(event, context):
    # Check if this is a scheduled event
    if event.get('source') == 'aws.events':
        logger.info("Running scheduled parse_feeds job")
        return parse_feeds_scheduled(event, context)
    
    # Handle background tasks
    if event.get('background_task'):
        task_path = event.get('task_path')
        args = event.get('args', [])
        kwargs = event.get('kwargs', {})

        logger.info(f"Running as a background task: {task_path} with args: {args} and kwargs: {kwargs}")

        try:
            execute_background_task(task_path, args, kwargs)
            return {
                'statusCode': 200, 
                'body': json.dumps('Background task completed')
            }
        except Exception as e:
            logger.error(f"Background task failed: {str(e)}", exc_info=True)
            return {
                'statusCode': 500, 
                'body': json.dumps(f'Background task failed: {str(e)}')
            }
    
    logger.info("Running as a normal API Gateway request")
    # Normal API Gateway request
    if "headers" not in event:
        event["headers"] = {}
    
    return serverless_wsgi.handle_request(app, event, context)

