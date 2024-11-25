# db/opensearch/article_repository.py

import time
import copy
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from opensearchpy import helpers

from lib.log import logger
from ..interfaces.database import ArticleRepository
from .repository import OpenSearchRepository

class OpenSearchArticleRepository(ArticleRepository):
    """OpenSearch implementation of ArticleRepository"""

    def __init__(self, client, index):
        self._client = client
        self._index = index
        self._base_repo = OpenSearchRepository(client, index)

    def get(self, article_id: str) -> Optional[Dict]:
        return self._base_repo.get(article_id)

    def addOrUpdate(self, article: Dict) -> Optional[Dict]:
        """Add or update article with vector handling"""
        try:
            # Check if article already exists
            existing = self._client.exists(index=self._index, id=article['id'])
            
            if existing:
                # Fetch existing document
                existing_doc = self._client.get(index=self._index, id=article['id'])['_source']
                
                # Check if summary_vector has changed
                new_vector = article.get('summary_vector')
                existing_vector = existing_doc.get('summary_vector')
                
                vector_changed = (
                    (new_vector is not None and existing_vector is None) or
                    (new_vector is None and existing_vector is not None) or
                    (new_vector is not None and existing_vector is not None and new_vector != existing_vector)
                )
                
                if vector_changed:
                    # Full update if vector changed
                    self._client.index(
                        index=self._index,
                        body=article,
                        id=article['id'],
                        refresh=True
                    )
                else:
                    # Partial update if vector unchanged
                    update_fields = {k: v for k, v in article.items() if k != 'summary_vector'}
                    self._client.update(
                        index=self._index,
                        id=article['id'],
                        body={'doc': update_fields},
                        refresh=True
                    )
            else:
                # New article
                self._client.index(
                    index=self._index,
                    body=article,
                    id=article['id'],
                    refresh=True
                )
            return article
        except Exception as e:
            logger.error(f"Error adding/updating article in OpenSearch: {str(e)}")
            return None

    def query_by_status(
        self, 
        status: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Query articles by processing status and date range"""
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"processing_status": status}}
                    ]
                }
            },
            "sort": [{"date_created": {"order": "desc"}}],
            "size": limit
        }

        if start_date and end_date:
            query["query"]["bool"]["must"].append({
                "range": {
                    "date_created": {
                        "gte": start_date,
                        "lte": end_date
                    }
                }
            })
        elif start_date:
            query["query"]["bool"]["must"].append({
                "range": {
                    "date_created": {
                        "gte": start_date
                    }
                }
            })
        elif end_date:
            query["query"]["bool"]["must"].append({
                "range": {
                    "date_created": {
                        "lte": end_date
                    }
                }
            })

        try:
            response = self._client.search(index=self._index, body=query)
            return [hit['_source'] for hit in response['hits']['hits']]
        except Exception as e:
            logger.error(f"Error querying articles from OpenSearch: {str(e)}")
            return []

    # Query articles using vector similarity
    def query_by_vector(
        self,
        vector: List[float],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Query articles using vector similarity"""
        initial_time = time.time()

        query = {
            "size": limit,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"processing_status": "audio_summary_generated"}}
                    ]
                }
            },
            "sort": [{"date_published": "desc"}]
        }

        if start_date or end_date:
            date_range = {"range": {"date_published": {}}}
            if start_date:
                date_range["range"]["date_published"]["gte"] = start_date
            if end_date:
                date_range["range"]["date_published"]["lte"] = end_date
            query["query"]["bool"]["filter"].append(date_range)

        if vector and len(vector) > 0:
            query["query"] = {
                "script_score": {
                    "query": query["query"],
                    "script": {
                        "source": "cosineSimilarity(params.query_vector, doc['summary_vector']) + 1.0",
                        "params": {"query_vector": vector}
                    }
                }
            }
            query["sort"] = [{"_score": "desc"}, {"date_published": "desc"}]

        # Create a copy of the query for logging
        log_query = copy.deepcopy(query)
        if vector and len(vector) > 0:
            if 'script_score' in log_query['query']:
                if 'params' in log_query['query']['script_score']['script']:
                    log_query['query']['script_score']['script']['params']['query_vector'] = '[vector omitted]'

        logger.debug(f"OpenSearch query: {json.dumps(log_query, indent=2)}")

        try:
            start_time = time.time()
            response = self._client.search(index=self._index, body=query)
            end_time = time.time()
            
            query_time = end_time - start_time
            logger.debug(f"OpenSearch query execution time: {query_time:.3f} seconds. total time: {time.time() - initial_time:.3f} seconds")
            
            logger.info(f"Retrieved {len(response['hits']['hits'])} articles between {start_date} and {end_date}")
            
            # Include the score in the returned results
            return [
                {**hit['_source'], 'score': hit['_score']}
                for hit in response['hits']['hits']
            ]
        except Exception as e:
            logger.error(f"Error querying articles from OpenSearch: {str(e)}")
            return []

    def search(self, query: Dict) -> List[Dict]:
        """Search articles using a query"""
        return self._client.search(index=self._index, body=query)

    # Does a full update of the article document
    def bulk_update(self, articles: List[Dict]) -> None:
        """Bulk update articles with full document replacement"""
        try:
            actions = [
                {
                    "_op_type": "index",
                    "_index": self._index,
                    "_id": article['id'],
                    "_source": article
                }
                for article in articles
            ]
            helpers.bulk(self._client, actions)
        except Exception as e:
            logger.error(f"Error bulk updating articles in OpenSearch: {str(e)}")

    # Does a partial update of the article document
    def bulk_update_partial(self, articles: List[Dict], exclude_fields: List[str] = ['summary_vector']) -> None:
        """Bulk update articles with partial updates, preserving specified fields"""
        try:
            actions = [
                {
                    "_op_type": "update",
                    "_index": self._index,
                    "_id": article['id'],
                    "doc": {k: v for k, v in article.items() if k not in exclude_fields}
                }
                for article in articles
            ]
            helpers.bulk(self._client, actions)
        except Exception as e:
            logger.error(f"Error bulk updating articles in OpenSearch: {str(e)}")

    def delete_by_date_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> tuple[int, Optional[str]]:
        """Delete articles within a date range"""
        query = {
            "query": {
                "bool": {
                    "must": []
                }
            }
        }

        if start_date or end_date:
            date_range = {"range": {"date_published": {}}}
            if start_date:
                date_range["range"]["date_published"]["gte"] = start_date
            if end_date:
                date_range["range"]["date_published"]["lte"] = end_date
            query["query"]["bool"]["must"].append(date_range)
        
        try:
            # Count matching documents
            count_response = self._client.count(index=self._index, body=query)
            total_docs = count_response['count']
            
            if total_docs == 0:
                return 0, "No articles found in the specified date range"
                
            # Delete matching documents
            response = self._client.delete_by_query(
                index=self._index,
                body=query,
                refresh=True
            )
            
            return response['deleted'], None
        except Exception as e:
            logger.error(f"Error deleting articles from OpenSearch: {str(e)}")
            return 0, str(e)
        
    def update_mapping(self, new_properties: Dict) -> tuple[bool, Optional[str]]:
        """Update the OpenSearch mapping with provided properties"""
        try:
            response = self._client.indices.put_mapping(
                index=self._index,
                body={
                    "properties": new_properties
                }
            )
            
            if response.get('acknowledged', False):
                return True, None
            else:
                return False, "Mapping update not acknowledged by OpenSearch"
                
        except Exception as e:
            logger.error(f"Error updating OpenSearch mapping: {str(e)}")
            return False, str(e)