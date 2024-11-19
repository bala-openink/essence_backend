# db/interfaces/database.py

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, List, Dict, Any, Union
from models.user import User

T = TypeVar('T')

class GenericRepository(ABC, Generic[T]):
    """Base interface for basic CRUD operations"""
    
    @abstractmethod
    def get(self, id: str) -> Optional[T]:
        """Retrieve an item by its ID"""
        pass

    @abstractmethod
    def add(self, item: T) -> Optional[T]:
        """Add a new item"""
        pass

    @abstractmethod
    def delete(self, id: str) -> bool:
        """Delete an item by its ID"""
        pass

    @abstractmethod
    def list(self, **kwargs) -> List[T]:
        """List items with optional filters"""
        pass

    @abstractmethod
    def update(self, item: T) -> Optional[T]:
        """Update an existing item"""
        pass

class ArticleRepository(ABC):
    """Interface for article-specific operations"""

    @abstractmethod
    def get(self, article_id: str) -> Optional[Dict]:
        """Get article by ID"""
        pass

    @abstractmethod
    def addOrUpdate(self, article: Dict) -> Optional[Dict]:
        """Add or update an article"""
        pass

    @abstractmethod
    def query_by_status(
        self, 
        status: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Query articles by processing status and date range"""
        pass

    @abstractmethod
    def query_by_vector(
        self,
        vector: List[float],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Query articles using vector similarity"""
        pass

    @abstractmethod
    def search(self, query: Dict) -> List[Dict]:
        """Search articles using a query"""
        pass

    @abstractmethod
    def bulk_update(self, articles: List[Dict]) -> None:
        """Bulk update articles"""
        pass

    @abstractmethod
    def bulk_update_partial(self, articles: List[Dict]) -> None:
        """Bulk update articles with partial updates"""
        pass

    @abstractmethod
    def delete_by_date_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> tuple[int, Optional[str]]:
        """Delete articles within a date range"""
        pass

class UserRepository(ABC):
    """Interface for user-specific operations"""

    @abstractmethod
    def get(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        pass

    @abstractmethod
    def add(self, user: User) -> Optional[User]:
        """Add or update a user"""
        pass

    @abstractmethod
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        pass

    @abstractmethod
    def update(self, user: User) -> Optional[User]:
        """Update user preferences"""
        pass

class UserFeedRepository(ABC):
    """Interface for user feed operations"""
    
    @abstractmethod
    def bulk_create(self, user_feeds: List[Dict[str, Any]]) -> None:
        """Bulk create user feeds"""
        pass
                
    @abstractmethod
    def delete_old_feeds(
        self,
        user_id: str,
        before_date: str
    ) -> int:
        """Delete user's old feed entries"""
        pass

    @abstractmethod
    def get_latest_news(
        self,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20,
        preferred_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get latest unsent news for user"""
        pass

    @abstractmethod
    def mark_feeds_as_sent(self, user_id: str, article_ids: List[str]) -> None:
        """Mark feeds as sent to user"""
        pass

class FeedBatchRepository(ABC):
    """Interface for feed batch operations"""
    
    @abstractmethod
    def get_batch(self, batch_id: str) -> Optional[Dict]:
        """Get batch by ID"""
        pass

    @abstractmethod
    def create_batch(self, batch_record: Dict) -> Optional[Dict]:
        """Create a new batch record"""
        pass

    @abstractmethod
    def update_batch_status(
        self,
        batch_id: str,
        stage: str,
        result: Optional[Dict] = None,
        error_msg: Optional[str] = None
    ) -> bool:
        """Update batch processing status"""
        pass

    @abstractmethod
    def mark_stage_complete(
        self,
        batch_id: str,
        stage: str,
        end_time: str
    ) -> bool:
        """Mark a processing stage as complete"""
        pass

class DatabaseClient(ABC):
    """Base interface for database clients"""
    
    @abstractmethod
    def connect(self) -> Any:
        """Establish database connection"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close database connection"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if database is connected"""
        pass