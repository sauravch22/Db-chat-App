"""Qdrant Vector Database Service"""

import hashlib
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import logging
from app.config import Settings
from typing import List, Dict

logger = logging.getLogger(__name__)

settings = Settings()


class VectorService:
    """Service for vector database operations"""
    
    def __init__(self):
        self.client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None
        )
        self.collection_name = settings.QDRANT_COLLECTION
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist"""
        
        try:
            # Check if collection exists
            self.client.get_collection(self.collection_name)
            logger.info(f"Collection {self.collection_name} already exists")
        except:
            # Create collection
            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=768,  # nomic-embed-text current version dimension
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"Created collection {self.collection_name}")
            except Exception as e:
                logger.error(f"Error creating collection: {str(e)}")
    
    async def upsert_vector(
        self,
        vector_id: str,
        embedding: List[float],
        metadata: Dict,
        table_name: str = None,
        database_name: str = None
    ):
        """Insert or update vector in database"""
        
        try:
            stable_uuid = str(uuid.UUID(hashlib.md5(vector_id.encode()).hexdigest()))
            point = PointStruct(
                id=stable_uuid,
                vector=embedding,
                payload={
                    "vector_id": vector_id,
                    "table_name": table_name,
                    "database_name": database_name,
                    **metadata
                }
            )
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            logger.debug(f"Upserted vector {vector_id}")
        
        except Exception as e:
            logger.error(f"Error upserting vector: {str(e)}")
            raise
    
    async def search(
        self,
        embedding: List[float],
        top_k: int = 5,
        filters: Dict = None
    ) -> List[Dict]:
        """Search vectors by embedding"""
        try:
            # Use Qdrant HTTP API directly for compatibility
            import httpx
            url = f"{settings.QDRANT_URL}/collections/{self.collection_name}/points/search"
            payload = {
                "vector": embedding,
                "limit": top_k,
                "with_payload": True
            }
            # Add filter if provided
            if filters:
                payload["filter"] = filters
                logger.info(f"Vector search with filter: {filters}")

            logger.debug(f"Searching Qdrant at {url} with limit={top_k}")
            r = httpx.post(url, json=payload, timeout=10.0)
            r.raise_for_status()
            data = r.json()
            results = data.get("result", [])

            logger.info(f"Vector search returned {len(results)} results")
            for i, item in enumerate(results[:3]):
                logger.debug(f"  Result {i+1}: score={item.get('score', 0):.3f}, table={item.get('payload', {}).get('table_name')}, type={item.get('payload', {}).get('type')}")

            return [
                {
                    "score": item.get("score"),
                    "payload": item.get("payload")
                }
                for item in results
            ]

        except Exception as e:
            logger.error(f"Error searching vectors: {str(e)}", exc_info=True)
            raise
    
    async def health_check(self) -> bool:
        """Check if Qdrant is running"""
        
        try:
            self.client.get_collections()
            return True
        except:
            return False
