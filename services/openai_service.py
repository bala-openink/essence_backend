from openai import OpenAI
from services import utilities

class OpenAIService:
    _instance = None
    _client = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._client = OpenAI(api_key=utilities.get_secret("OPENAI_API_KEY"))

    @property
    def client(self):
        return self._client

# Create a global instance
openai_service = OpenAIService.get_instance()

