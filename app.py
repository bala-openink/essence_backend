from flask import Flask, request, jsonify, make_response, Response, stream_with_context
from werkzeug.exceptions import BadRequest
from flask import Flask, request, send_file, jsonify
from pydub import AudioSegment
from io import BytesIO
import time
import uuid

import serverless_wsgi
import traceback

from services import util, summarizer, podcaster, feed_reader, user_news
from lib import db
from lib.log import logger

from models import AudioStoryRequest

app = Flask(__name__)

localMode = True


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
    clean_url = util.clean_url(url)
    # TODO P1 - Audio should be generated in the background and be responded in an async way
    # TODO P2 - Stream the response back in a continuous way, using websocket like approach
    # Unique id for the article is generated to cache in the DB. When ID changes, new summary is performed. Hence the importance of Id
    # TODO THINK - Do we want to include instructions and include_audio in the ID ?
    id = util.generate_id(url, instructions, include_audio)
    # check if this article exists in the db, and return the object
    item = None
    if is_test is None:
        item = db.get_summary_table().get(id)

        if item and item["text_summary"]:
            logger.info(f"article {id} found in the DB. Returning")
            # Log that this user has requested for this article
            util.log_user_activity(user_id, id, clean_url)
            return Response(util.build_response(id, item), headers=headers)

    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = util.is_worth(id, clean_url)

    if isWorth:
        logger.info(f"Article {id} doesn't exist and its worth. Going to summarize")
        try:
            util.log_user_activity(user_id, id, clean_url, "CREATE")
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
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"  # Disable buffering for Nginx
    }

    # Get transcript if not provided in the request
    if not transcript or len(str(transcript)) < 100:
        transcript = util.extract_transcript(url)
    
    if len(str(transcript)) < 100:
        raise BadRequest("Transcript could not be extracted. URL might be incorrect")


    # ID is a hash of the clean url after removing query params
    clean_url = util.clean_url(url)
    # TODO P1 - Audio should be generated in the background and be responded in an async way
    # TODO P2 - Stream the response back in a continuous way, using websocket like approach
    # Unique id for the article is generated to cache in the DB. When ID changes, new summary is performed. Hence the importance of Id
    # TODO THINK - Do we want to include instructions and include_audio in the ID ?
    id = util.generate_id(url)
    # check if this article exists in the db, and return the object
    item = None
    if is_test is None:
        item = db.get_summary_table().get(id)

        if item and item.get("text_summary"):
            logger.info(f"article {id} found in the DB. Returning")
            # Log that this user has requested for this article
            util.log_user_activity(user_id, id, clean_url)
            return Response(util.build_response(id, item), headers=headers)

    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = util.is_worth(id, clean_url)

    if isWorth:
        logger.info(f"Article {id} doesn't exist and its worth. Going to summarize")
        try:
            util.log_user_activity(user_id, id, clean_url, "CREATE")
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
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"  # Disable buffering for Nginx
    }

    # ID is a hash of the clean url after removing query params
    clean_url = util.clean_url(url)
    # TODO P1 - Audio should be generated in the background and be responded in an async way
    # TODO P2 - Stream the response back in a continuous way, using websocket like approach
    # Unique id for the article is generated to cache in the DB. When ID changes, new summary is performed. Hence the importance of Id
    # TODO THINK - Do we want to include instructions and include_audio in the ID ?
    id = util.generate_id(url)
    # check if this article exists in the db, and return the object
    item = None
    if is_test is None:
        item = db.get_summary_table().get(id)
        logger.info(f"article {id} found in the DB")

        if item and item.get("audio_summary_url"):
            logger.info(f"article {id} found in the DB. Returning")
            return Response(util.build_response(id, item), headers=headers)

    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = util.is_worth(id, clean_url)

    if isWorth:
        logger.info(f"Article {id} doesn't exist and its worth. Going to do inference")
        try:
            util.log_user_activity(user_id, id, clean_url, "CREATE")
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

        s3_url = util.upload_audio_to_s3(audio_story_request, output)

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
        two_speakers = request.args.get('two_speakers', default='true').lower() == 'true'

        # Generate intro audio using the implementation function
        intro_segment = podcaster.generate_intro_audio(userName=user_name, twoSpeakers=two_speakers)

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


##################################################################################
# ######## USER FACING ENDPOINTS #######################################################
##################################################################################

@app.route('/latest_news', methods=['GET'])
def latest_news():
    logger.info("latest_news route")
    try:
        user_id = request.args.get('user_id')
        categories = request.args.getlist('category')
        limit = int(request.args.get('limit', 10))

        if not user_id:
            raise BadRequest("user_id is required")

        articles = user_news.get_latest_news(user_id, categories, limit)

        return jsonify({
            "count": len(articles),
            "articles": articles
        }), 200

    except Exception as e:
        logger.error(f"Error fetching latest news: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


##################################################################################
# ######## TESTING ENDPOINTS #####################################################
##################################################################################

@app.route('/test/articles', methods=['GET'])
def test_articles():
    request_id = str(uuid.uuid4())
    logger.info(f"test_articles route - Request ID: {request_id}")
    try:
        # Get optional parameters
        limit = request.args.get('limit', default=None, type=int)
        all_attributes = request.args.get('all_attributes', default='false').lower() == 'true'

        table = db.get_article_table()
        items = table.list()

        # Extract desired fields
        results = []
        for item in items:
            if all_attributes:
                result = item.copy()
                if 'full_text' in result:
                    # Trim full_text to 50 words
                    result['full_text'] = ' '.join(result['full_text'].split()[:50]) + '...'
            else:
                result = {
                    'id': item.get('id'),
                    'title': item.get('title'),
                    'url': item.get('url'),
                    'processing_status': item.get('processing_status'),
                    'date_published': item.get('date_published')
                }
            results.append(result)

        # Apply limit if specified
        if limit is not None:
            results = results[:limit]

        list_size = len(results)
        logger.info(f"Fetched {list_size} articles from DynamoDB - Request ID: {request_id}")
        
        # Include the list size in the response
        response = {
            'count': list_size,
            'articles': results
        }
        
        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)} - Request ID: {request_id}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    

def handler(event, context):
    # TODO - Check how to pass the headers from API gateway when required.
    if "headers" not in event:
        event["headers"] = {}
    return serverless_wsgi.handle_request(app, event, context)