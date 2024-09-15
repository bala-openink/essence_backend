# File for all Models

class AudioStoryRequest:
    def __init__(self,  id, text_summary, url=None, length="short", language="en", region="UK", 
                 two_speakers=True, add_background=False, user_name=None):
        self.id = id
        self.text_summary = text_summary
        self.url = url
        self.length = length
        self.language = language
        self.region = region
        self.two_speakers = two_speakers
        self.add_background = add_background
        self.user_name = user_name
