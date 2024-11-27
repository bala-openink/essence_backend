from datetime import datetime
import uuid
from decimal import Decimal

class User:
    def __init__(self, email, first_name, country, language, id=None, status='unverified',
                 verification_code=None, tokens=None, preferences=None, created_at=None, updated_at=None,
                 intro_audio_urls=None, category=None, news_sources=None):
        self.id = id or str(uuid.uuid4())
        self.email = email.lower()
        self.first_name = first_name.capitalize()
        self.country = country.upper()
        self.language = language.upper()
        self.status = status
        self.verification_code = verification_code
        self.tokens = tokens or []
        self.preferences = preferences or {}
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.intro_audio_urls = intro_audio_urls or {}
        self.category = category
        self.news_sources = news_sources or []
        
    def to_dict(self):
        preferences_dict = self.preferences.copy() if self.preferences else {}
        
        # Truncate vector representations and convert Decimals to floats for JSON serialization
        if 'flat_vector' in preferences_dict:
            vector = preferences_dict['flat_vector']
            preferences_dict['flat_vector'] = [float(x) for x in vector[:5]]
        
        if 'structured_vector' in preferences_dict:
            vector = preferences_dict['structured_vector']
            preferences_dict['structured_vector'] = [float(x) for x in vector[:5]]

        # Convert category set to list if it exists
        category = getattr(self, 'category', None)
        if isinstance(category, set):
            category = list(category)

        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'country': self.country,
            'language': self.language,
            'status': self.status,
            'verification_code': self.verification_code,
            'preferences': preferences_dict,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'intro_audio_urls': self.intro_audio_urls,
            'category': category,
            'news_sources': self.news_sources
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            email=data['email'],
            first_name=data['first_name'],
            country=data.get('country'),
            language=data.get('language'),
            id=data['id'],
            status=data.get('status', 'unverified'),
            verification_code=data.get('verification_code'),
            tokens=data.get('tokens', []),
            preferences=data.get('preferences', {}),
            created_at=datetime.fromisoformat(data['created_at']) if 'created_at' in data else None,
            updated_at=datetime.fromisoformat(data['updated_at']) if 'updated_at' in data else None,
            intro_audio_urls=data.get('intro_audio_urls', {}),
            category=data.get('category'),
            news_sources=data.get('news_sources', [])
        )

    def to_dynamo_dict(self):
        """Convert user object to DynamoDB-compatible dictionary (preserving Decimals)"""
        # Use the original preferences dict without float conversion
        preferences_dict = self.preferences.copy() if self.preferences else {}
        
        # Convert category set to list if it exists
        category = getattr(self, 'category', None)
        if isinstance(category, set):
            category = list(category)

        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'country': self.country,
            'language': self.language,
            'status': self.status,
            'verification_code': self.verification_code,
            'tokens': self.tokens,
            'preferences': preferences_dict,  # Keeps Decimals intact
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'intro_audio_urls': self.intro_audio_urls,
            'category': category,
            'news_sources': self.news_sources
        }
