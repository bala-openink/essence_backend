# db/opensearch/repository.py

import time
import copy
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from lib.log import logger
from ..interfaces.database import GenericRepository

class OpenSearchRepository(GenericRepository[Dict[str, Any]]):
    """Generic OpenSearch repository implementation"""

    def __init__(self, client, index):
        self._client = client
        self._index = index

    def get(self, id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID"""
        try:
            response = self._client.get(index=self._index, id=id)
            return response['_source']
        except Exception as e:
            logger.error(f"Error getting document from OpenSearch: {str(e)}")
            return None

    def add(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Add new document"""
        try:
            if not item or 'id' not in item:
                raise ValueError('Invalid item')
            
            self._client.index(
                index=self._index,
                body=item,
                id=item['id'],
                refresh=True
            )
            return item
        except Exception as e:
            logger.error(f"Error adding document to OpenSearch: {str(e)}")
            return None

    def delete(self, id: str) -> bool:
        """Delete document by ID"""
        try:
            self._client.delete(index=self._index, id=id, refresh=True)
            return True
        except Exception as e:
            logger.error(f"Error deleting document from OpenSearch: {str(e)}")
            return False

    def list(self, **kwargs) -> List[Dict[str, Any]]:
        """List documents with optional filters"""
        try:
            query = {"query": {"match_all": {}}}
            if kwargs:
                must = []
                for key, value in kwargs.items():
                    must.append({"term": {key: value}})
                query = {"query": {"bool": {"must": must}}}

            response = self._client.search(index=self._index, body=query)
            return [hit['_source'] for hit in response['hits']['hits']]
        except Exception as e:
            logger.error(f"Error listing documents from OpenSearch: {str(e)}")
            return []

    def update(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update existing document"""
        try:
            if not item or 'id' not in item:
                raise ValueError('Invalid item for update')

            # Check if document exists
            exists = self._client.exists(index=self._index, id=item['id'])
            if exists:
                self._client.update(
                    index=self._index,
                    id=item['id'],
                    body={'doc': item},
                    refresh=True
                )
            else:
                return self.add(item)
            return item
        except Exception as e:
            logger.error(f"Error updating document in OpenSearch: {str(e)}")
            return None

    def bulk_update(self, items: List[Dict[str, Any]]) -> None:
        """Bulk update documents"""
        try:
            actions = [
                {
                    "_op_type": "index",
                    "_index": self._index,
                    "_id": item['id'],
                    "_source": item
                }
                for item in items
            ]
            helpers.bulk(self._client, actions)
        except Exception as e:
            logger.error(f"Error bulk updating documents in OpenSearch: {str(e)}")
            raise

    def delete_by_query(self, query: Dict[str, Any]) -> tuple[int, Optional[str]]:
        """Delete documents by query"""
        try:
            # First, count matching documents
            count_response = self._client.count(index=self._index, body=query)
            total_docs = count_response['count']
            
            if total_docs == 0:
                return 0, "No documents found matching the query"
                
            # Delete matching documents
            response = self._client.delete_by_query(
                index=self._index,
                body=query,
                refresh=True
            )
            
            return response['deleted'], None
        except Exception as e:
            logger.error(f"Error deleting documents from OpenSearch: {str(e)}")
            return 0, str(e)