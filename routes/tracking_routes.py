from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.event import Event
from lib.log import logger
from werkzeug.exceptions import BadRequest
from services.utilities import process_events
from db.factory import db_factory

tracking_bp = Blueprint('tracking', __name__)

user_repository = db_factory.get_user_repository()

@tracking_bp.route('/track-event', methods=['POST'])
@jwt_required()
def track_events():
    user_id = get_jwt_identity()
    user = user_repository.get(user_id)
    if not user:
        raise BadRequest("User not found")
    
    events_data = request.json.get('events', [])
    events = []
    
    for event in events_data:
        # Validate current_news_index
        try:
            current_news_index = int(event.get('currentNewsIndex', 0))
        except (ValueError, TypeError):
            current_news_index = 0

        # Validate audio_playback_time
        try:
            audio_playback_time = float(event.get('audioPlaybackTime', 0.0))
        except (ValueError, TypeError):
            audio_playback_time = 0.0

        new_event = Event(
            user_id=user_id,
            user_email=user.email,
            event_type=event.get('eventType'),
            news_item_id=event.get('newsItemId'),
            news_item_title=event.get('newsItemTitle'),
            current_news_index=current_news_index,
            audio_playback_time=audio_playback_time,
            additional_data=event.get('additionalData')
        )
        events.append(new_event)
        logger.info(f"Event prepared for processing: {new_event.to_dict()}")

    # Process and flush events to S3
    process_events(events)

    return jsonify({"message": f"Successfully processed {len(events_data)} events"}), 200
