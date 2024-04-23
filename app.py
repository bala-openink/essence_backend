from flask import Flask, request, jsonify, make_response
from werkzeug.exceptions import BadRequest

import serverless_wsgi

import os
import traceback

from services import util, summarizer
from lib import db, log

app = Flask(__name__)

logger = log.setup_logger()
localMode = True

@app.route('/')
def home():
    logger.info("Default route")
    return jsonify({"message": "Hi there! Welcome to One click summarizer."})


# Main Endpoint for transcript to summary. For use in text blogs.
# Client to provide a hash of the url as id, and the complete transcript as content.
# TODO - better error handling.
@app.route("/summarize", methods=["POST"])
def summarize():
    logger.info("summarize route")

    body = request.get_json()
    if body is None:
        raise BadRequest("No JSON body received")

    url = body.get("url")
    transcript = body.get("transcript")
    is_test = body.get("test")
    user_id = body.get("user_id")

    # validate the input
    if not url:
        raise BadRequest("URL is required")
    if not transcript:
        raise BadRequest("Transcript is required")
    if len(str(transcript)) < 100:
        raise BadRequest("Transcript is too small")

    # TODO Get some details about the article. Platform, likes, comments, etc whatever possible

    # ID is a hash of the clean url after removing query params
    id, clean_url = util.hash_url(url)
    # check if this article exists in the db, and return the object
    if is_test is None:
        item = db.get_summary_table().get(id)

        if item:
            logger.info(f"article {id} found in the DB. Returning")
            # Log that this user has requested for this article
            util.log_user_activity(user_id, id, clean_url)

            summary_url = item["audio_summary_url"]
            text_summary = item["text_summary"]
            if summary_url or text_summary:
                return util.build_response(id, summary_url, text_summary, item['url'])
        
    # If summary url is not present, continue processing again
    # check if its worth the effort
    isWorth = util.is_worth(id, transcript)

    if isWorth:
        logger.info(
            f"Article {id} doesn't exist and its worth. Going to summarize"
        )
        # start the process for extracting summary
        try:
            item = summarizer.process_transcript(user_id, id, clean_url, transcript, localMode)
            util.log_user_activity(user_id, id, clean_url, "CREATE")

            return util.build_response(id, item['audio_summary_url'], item['text_summary'], item['url'])
        except Exception as e:
            traceback.print_exc()
            # Return a not found response if the audio file doesn't exist
            return make_response(jsonify({'error': 'Error creating the summary for this article'}), 404, {"Content-Type": "application/json"})

    else:
        # TODO: On success this API will return an audio file. On failure, we should return a http error response with message
        return make_response(jsonify({'error': 'Sorry. We don\'t support summary for this article now'}), 404, {"Content-Type": "application/json"})


def handler(event, context):
    # TODO - Check how to pass the headers from API gateway when required.
    if 'headers' not in event:
        event['headers'] = {}
    return serverless_wsgi.handle_request(app, event, context)

# if __name__ == '__main__':
#     # Run the Flask app on the port provided by AWS Lambda (or default to 8080)
#     port = int(os.environ.get('PORT', 80))
#     # Enable/disable debug mode based on an environment variable
#     debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
#     app.run(host='0.0.0.0', port=port, debug=debug_mode)
