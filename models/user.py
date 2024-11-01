from datetime import datetime
import uuid
from decimal import Decimal

class User:
    def __init__(self, email, first_name, country, language, id=None, status='unverified',
                 verification_code=None, tokens=None, preferences=None, created_at=None, updated_at=None,
                 intro_audio_urls=None):
        self.id = id or str(uuid.uuid4())
        self.email = email
        self.first_name = first_name
        self.country = country
        self.language = language
        self.status = status
        self.verification_code = verification_code
        self.tokens = tokens or []
        self.preferences = preferences or {}
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.intro_audio_urls = intro_audio_urls or {}

    def to_dict(self):
        preferences_dict = self.preferences.copy() if self.preferences else {}
        
        # Truncate vector representations
        if 'flat_vector' in preferences_dict:
            preferences_dict['flat_vector'] = preferences_dict['flat_vector'][:5] + ['...']
        if 'structured_vector' in preferences_dict:
            preferences_dict['structured_vector'] = preferences_dict['structured_vector'][:5] + ['...']

        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'country': self.country,
            'language': self.language,
            'status': self.status,
            'verification_code': self.verification_code,
            'tokens': self.tokens,
            'preferences': preferences_dict,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'intro_audio_urls': self.intro_audio_urls
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
            intro_audio_urls=data.get('intro_audio_urls', {})
        )
