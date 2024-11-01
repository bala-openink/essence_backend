from models.user import User
from db.db import get_user_table
from lib.log import logger

class UserRepository:
    def __init__(self):
        self._table = get_user_table()

    def create(self, user: User):
        self._table.add(user)
        return user

    def get_by_id(self, user_id: str) -> User:
        user_dict = self._table.get(user_id)
        return User.from_dict(user_dict) if user_dict else None

    def get_by_email(self, email: str) -> User:
        user_dict = self._table.get_user_by_email(email)
        return User.from_dict(user_dict) if user_dict else None

    def update(self, user: User):
        self._table.addOrUpdate(user)
        return user

    def delete(self, user_id: str):
        self._table.delete(user_id)

    def add_token(self, user_id: str, token_data: dict):
        user = self.get_by_id(user_id)
        if user:
            user.tokens.append(token_data)
            self.update(user)
        else:
            logger.error(f"User not found for ID: {user_id}")

    def remove_token(self, user_id: str, jti: str):
        user = self.get_by_id(user_id)
        if user:
            user.tokens = [t for t in user.tokens if t['jti'] != jti]
            self.update(user)
        else:
            logger.error(f"User not found for ID: {user_id}")

    def remove_all_tokens(self, user_id: str):
        user = self.get_by_id(user_id)
        if user:
            user.tokens = []
            self.update(user)
        else:
            logger.error(f"User not found for ID: {user_id}")

