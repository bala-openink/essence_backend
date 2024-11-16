class AudioStoryRequest:
    def __init__(
        self,
        id,
        text_summary,
        url=None,
        length="short",
        language="en",
        region="UK",
        two_speakers=True,
        add_background=False,
        user_name=None,
        previous_article=None,
        new_instructions=None
    ):
        self.id = id
        self.text_summary = text_summary
        self.url = url
        self.length = length
        self.language = language
        self.region = region
        self.two_speakers = two_speakers
        self.add_background = add_background
        self.user_name = user_name
        self.previous_article = previous_article
        self.new_instructions = new_instructions

    def to_dict(self):
        return {
            "id": self.id,
            "text_summary": self.text_summary,
            "url": self.url,
            "length": self.length,
            "language": self.language,
            "region": self.region,
            "two_speakers": self.two_speakers,
            "add_background": self.add_background,
            "user_name": self.user_name,
            "previous_article": self.previous_article,
            "new_instructions": self.new_instructions
        }
