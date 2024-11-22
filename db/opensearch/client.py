# db/opensearch/client.py

from typing import Optional, Dict, Any
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from requests_aws4auth import AWS4Auth

from lib.log import logger
from services.utilities import get_secret
from ..interfaces.database import DatabaseClient
import config
import constants

class OpenSearchClient(DatabaseClient):
    """OpenSearch client management"""
    
    def __init__(self, local: bool = False, stage: str = constants.STAGE_LOCAL):
        self.local = local
        self.stage = stage
        self._client = None
        
    def connect(self) -> 'OpenSearchClient':
        """Create OpenSearch client and initialize indices"""
        if self.local:
            self._client = OpenSearch(
                hosts=[{'host': config.OPENSEARCH_HOST, 'port': config.OPENSEARCH_PORT}],
                http_auth=(config.OPENSEARCH_USERNAME, config.OPENSEARCH_PASSWORD),
                use_ssl=False,
                verify_certs=False,
                ssl_show_warn=False,
                connection_class=RequestsHttpConnection
            )
        else:
            opensearch_password = get_secret(secret_key='OPENSEARCH_PASSWORD', default_value=None)
            self._client = OpenSearch(
                hosts=[{'host': config.OPENSEARCH_HOST, 'port': config.OPENSEARCH_PORT}],
                http_auth=(config.OPENSEARCH_USERNAME, opensearch_password),
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection
            )
        
        # Initialize indices after connection
        self._initialize_indices()
        return self

    def _initialize_indices(self) -> None:
        """Initialize all required OpenSearch indices"""
        if not self._client:
            raise RuntimeError("OpenSearch client not initialized")
            
        # Initialize article index with stage suffix
        index_name = f"{config.OPENSEARCH_INDEX}_{self.stage}"
        self.create_index_if_not_exists(
            index_name,
            self.get_article_index_mapping()
        )

    def disconnect(self) -> None:
        """Close OpenSearch connection"""
        self._client = None

    def is_connected(self) -> bool:
        """Check if OpenSearch is connected"""
        return self._client is not None

    def get_client(self) -> Optional[OpenSearch]:
        """Get OpenSearch client"""
        if not self._client:
            self.connect()
        return self._client

    def create_index_if_not_exists(self, index_name: str, mapping: Dict) -> None:
        """Create index if it doesn't exist"""
        if not self._client.indices.exists(index=index_name):
            self._client.indices.create(index=index_name, body=mapping)
            logger.info(f"Created OpenSearch index: {index_name}")

    def get_article_index_mapping(self) -> Dict[str, Any]:
        """Get article index mapping"""
        return {
            "settings": {
                "index": {
                    "knn": True
                }
            },
            "mappings": {
                "properties": {
                    "article_id": {"type": "keyword"},
                    "summary_vector": {
                        "type": "knn_vector",
                        "dimension": 1536
                    },
                    "summary_200": {"type": "text"},
                    "summary_50": {"type": "text"},
                    "title": {"type": "text"},
                    "url": {"type": "keyword"},
                    "image": {"type": "keyword"},
                    "date_published": {"type": "date"},
                    "date_created": {"type": "date"},
                    "rss_summary": {"type": "text"},
                    "source_name": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "function": {
                        "type": "text",
                        "fields": {
                            "raw": {
                                "type": "keyword"
                            }
                        }
                    },
                    "industry": {
                        "type": "text",
                        "fields": {
                            "raw": {
                                "type": "keyword"
                            }
                        }
                    },
                    "region": {"type": "keyword"},
                    "domain": {"type": "keyword"},
                    "importance_score": {"type": "float"},
                    "single_news_item": {"type": "boolean"},
                    "categories": {"type": "keyword"},
                    "audio_summary": {"type": "text"},
                    "processing_status": {"type": "keyword"}
                }
            }
        }