from datetime import datetime
import uuid

class Event:
    def __init__(self, user_id, user_email, event_type, news_item_id, news_item_title, current_news_index, 
                  audio_playback_time, additional_data=None):
        self.id = str(uuid.uuid4())
        self.user_id = user_id
        self.user_email = user_email
        self.event_type = event_type
        self.news_item_id = news_item_id
        self.news_item_title = news_item_title
        self.current_news_index = current_news_index
        self.audio_playback_time = audio_playback_time
        self.additional_data = additional_data
        self.created_at = datetime.utcnow().isoformat(timespec='microseconds') + 'Z'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'event_type': self.event_type,
            'news_item_id': self.news_item_id,
            'news_item_title': self.news_item_title,
            'current_news_index': self.current_news_index,
            'audio_playback_time': self.audio_playback_time,
            'additional_data': self.additional_data,
            "created_at": self.created_at
        }
