from flask import Flask, request, jsonify, make_response, Response, stream_with_context
from werkzeug.exceptions import BadRequest

import serverless_wsgi

import os
import time
import traceback

from services import util, summarizer
from lib import db, log

app = Flask(__name__)

logger = log.setup_logger()
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


def handler(event, context):
    # TODO - Check how to pass the headers from API gateway when required.
    if "headers" not in event:
        event["headers"] = {}
    return serverless_wsgi.handle_request(app, event, context)


