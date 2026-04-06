"""Unified NoSQL service — MongoDB, Redis, Elasticsearch, Neo4j.

Each database type translates natural-language via the LLM into its native
query language (aggregation pipeline, Redis commands, ES DSL, Cypher).
Schema introspection is provided where possible.
"""

import json
import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ── MongoDB ─────────────────────────────────────────────

class MongoHandler:
    """Handles MongoDB connections, schema sampling, and query execution."""

    def __init__(self, uri: str, database: str):
        self.uri = uri
        self.database = database

    def _get_client(self):
        from pymongo import MongoClient
        return MongoClient(self.uri, serverSelectionTimeoutMS=10000)

    def test_connection(self) -> dict:
        try:
            client = self._get_client()
            client.admin.command("ping")
            client.close()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def extract_schema(self) -> dict:
        """Sample documents to infer collection schemas."""
        client = self._get_client()
        db = client[self.database]
        collections = db.list_collection_names()
        schema = {"database": self.database, "collections": []}
        for name in collections:
            coll = db[name]
            count = coll.estimated_document_count()
            sample = list(coll.find().limit(5))
            fields = {}
            for doc in sample:
                for k, v in doc.items():
                    if k == "_id":
                        fields[k] = "ObjectId"
                    else:
                        fields[k] = type(v).__name__
            schema["collections"].append({
                "name": name,
                "document_count": count,
                "fields": fields,
                "sample": [_mongo_serialize(d) for d in sample[:2]],
            })
        client.close()
        return schema

    def execute_pipeline(self, collection: str, pipeline: list) -> dict:
        """Execute a MongoDB aggregation pipeline."""
        client = self._get_client()
        db = client[self.database]
        try:
            results = list(db[collection].aggregate(pipeline))
            serialized = [_mongo_serialize(r) for r in results[:500]]
            columns = list(serialized[0].keys()) if serialized else []
            return {"success": True, "rows": serialized, "columns": columns,
                    "row_count": len(serialized)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            client.close()

    def execute_find(self, collection: str, filter_doc: dict = None,
                     projection: dict = None, limit: int = 100) -> dict:
        client = self._get_client()
        db = client[self.database]
        try:
            cursor = db[collection].find(filter_doc or {}, projection or {}).limit(limit)
            results = [_mongo_serialize(r) for r in cursor]
            columns = list(results[0].keys()) if results else []
            return {"success": True, "rows": results, "columns": columns,
                    "row_count": len(results)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            client.close()


def _mongo_serialize(doc: dict) -> dict:
    """Convert MongoDB BSON types to JSON-safe values."""
    out = {}
    for k, v in doc.items():
        if hasattr(v, '__str__') and type(v).__name__ == 'ObjectId':
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, bytes):
            out[k] = v.decode("utf-8", errors="replace")
        elif isinstance(v, dict):
            out[k] = _mongo_serialize(v)
        elif isinstance(v, list):
            out[k] = [_mongo_serialize(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


# ── Redis ───────────────────────────────────────────────

class RedisHandler:
    """Handles Redis connections and command execution."""

    def __init__(self, url: str):
        self.url = url

    def _get_client(self):
        import redis as redis_lib
        return redis_lib.from_url(self.url, decode_responses=True, socket_timeout=10)

    def test_connection(self) -> dict:
        try:
            r = self._get_client()
            r.ping()
            r.close()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_info(self) -> dict:
        r = self._get_client()
        try:
            info = r.info()
            db_info = {k: v for k, v in info.items() if k.startswith("db")}
            keyspace = {}
            for db_key, db_val in db_info.items():
                if isinstance(db_val, dict):
                    keyspace[db_key] = db_val
            return {
                "version": info.get("redis_version", ""),
                "used_memory_human": info.get("used_memory_human", ""),
                "connected_clients": info.get("connected_clients", 0),
                "total_keys": sum(v.get("keys", 0) for v in keyspace.values()) if keyspace else info.get("db0", {}).get("keys", 0),
                "keyspace": keyspace,
            }
        finally:
            r.close()

    def extract_schema(self) -> dict:
        """Sample keys to understand data patterns."""
        r = self._get_client()
        try:
            info = self.get_info()
            cursor, keys = r.scan(match="*", count=200)
            key_types = {}
            samples = {}
            for key in keys[:100]:
                try:
                    ktype = r.type(key)
                    key_types[ktype] = key_types.get(ktype, 0) + 1
                    if ktype not in samples:
                        if ktype == "string":
                            samples[ktype] = {"key": key, "value": r.get(key)[:200] if r.get(key) else None}
                        elif ktype == "hash":
                            samples[ktype] = {"key": key, "fields": list(r.hgetall(key).keys())[:10]}
                        elif ktype == "list":
                            samples[ktype] = {"key": key, "length": r.llen(key)}
                        elif ktype == "set":
                            samples[ktype] = {"key": key, "size": r.scard(key)}
                        elif ktype == "zset":
                            samples[ktype] = {"key": key, "size": r.zcard(key)}
                except Exception:
                    continue
            return {"database": "redis", "info": info, "key_types": key_types,
                    "samples": samples, "sampled_keys": len(keys)}
        finally:
            r.close()

    def execute_command(self, command: str) -> dict:
        """Execute a Redis command string (read-only commands only)."""
        BLOCKED = {"del", "flushdb", "flushall", "set", "hset", "lpush",
                    "rpush", "sadd", "zadd", "expire", "rename", "move",
                    "persist", "config", "shutdown", "debug", "eval"}
        parts = command.strip().split()
        if not parts:
            return {"success": False, "error": "Empty command"}
        cmd = parts[0].lower()
        if cmd in BLOCKED:
            return {"success": False, "error": f"Write command '{cmd}' is blocked for safety"}
        r = self._get_client()
        try:
            result = r.execute_command(*parts)
            if isinstance(result, (list, tuple)):
                rows = [{"index": i, "value": str(v)} for i, v in enumerate(result)]
                return {"success": True, "rows": rows, "columns": ["index", "value"],
                        "row_count": len(rows)}
            elif isinstance(result, dict):
                rows = [{"key": k, "value": str(v)} for k, v in result.items()]
                return {"success": True, "rows": rows, "columns": ["key", "value"],
                        "row_count": len(rows)}
            else:
                return {"success": True, "rows": [{"result": str(result)}],
                        "columns": ["result"], "row_count": 1}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            r.close()


# ── Elasticsearch ───────────────────────────────────────

class ElasticsearchHandler:
    """Handles Elasticsearch connections and DSL query execution."""

    def __init__(self, url: str, api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def _get_client(self):
        from elasticsearch import Elasticsearch
        kwargs = {"hosts": [self.url], "request_timeout": 15}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return Elasticsearch(**kwargs)

    def test_connection(self) -> dict:
        try:
            es = self._get_client()
            info = es.info()
            es.close()
            return {"ok": True, "version": info.get("version", {}).get("number", "")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def extract_schema(self) -> dict:
        es = self._get_client()
        try:
            indices = es.cat.indices(format="json")
            schema = {"database": "elasticsearch", "indices": []}
            for idx in indices:
                name = idx.get("index", "")
                if name.startswith("."):
                    continue
                mapping = es.indices.get_mapping(index=name)
                props = {}
                if name in mapping:
                    props = mapping[name].get("mappings", {}).get("properties", {})
                fields = {k: v.get("type", "object") for k, v in props.items()}
                schema["indices"].append({
                    "name": name,
                    "doc_count": int(idx.get("docs.count", 0)),
                    "size": idx.get("store.size", ""),
                    "fields": fields,
                })
            es.close()
            return schema
        except Exception as e:
            logger.error("ES schema extraction failed: %s", e)
            if 'es' in dir():
                es.close()
            return {"database": "elasticsearch", "indices": [], "error": str(e)}

    def execute_query(self, index: str, query_body: dict, size: int = 100) -> dict:
        es = self._get_client()
        try:
            result = es.search(index=index, body=query_body, size=size)
            hits = result.get("hits", {}).get("hits", [])
            rows = []
            for h in hits:
                row = {"_id": h["_id"], "_score": h.get("_score")}
                row.update(h.get("_source", {}))
                rows.append(row)
            aggs = result.get("aggregations", {})
            if aggs and not rows:
                rows = _flatten_aggs(aggs)
            columns = list(rows[0].keys()) if rows else []
            return {"success": True, "rows": rows, "columns": columns,
                    "row_count": len(rows),
                    "total_hits": result.get("hits", {}).get("total", {}).get("value", 0)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            es.close()


def _flatten_aggs(aggs: dict) -> list:
    """Convert ES aggregation buckets into flat rows."""
    rows = []
    for agg_name, agg_val in aggs.items():
        buckets = agg_val.get("buckets", [])
        if buckets:
            for b in buckets:
                row = {agg_name: b.get("key"), "doc_count": b.get("doc_count", 0)}
                for sub_k, sub_v in b.items():
                    if isinstance(sub_v, dict) and "value" in sub_v:
                        row[sub_k] = sub_v["value"]
                rows.append(row)
        elif "value" in agg_val:
            rows.append({agg_name: agg_val["value"]})
    return rows


# ── Neo4j ───────────────────────────────────────────────

class Neo4jHandler:
    """Handles Neo4j connections and Cypher query execution."""

    def __init__(self, uri: str, username: str = "neo4j", password: str = ""):
        self.uri = uri
        self.username = username
        self.password = password

    def _get_driver(self):
        from neo4j import GraphDatabase
        return GraphDatabase.driver(self.uri, auth=(self.username, self.password))

    def test_connection(self) -> dict:
        try:
            driver = self._get_driver()
            with driver.session() as session:
                session.run("RETURN 1")
            driver.close()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def extract_schema(self) -> dict:
        driver = self._get_driver()
        try:
            with driver.session() as session:
                labels = [r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label").data()]
                rel_types = [r["relationshipType"] for r in session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType").data()]
                node_props = {}
                for label in labels:
                    try:
                        sample = session.run(f"MATCH (n:`{label}`) RETURN n LIMIT 3").data()
                        props = {}
                        for rec in sample:
                            node = rec.get("n", {})
                            for k, v in node.items():
                                props[k] = type(v).__name__
                        count_res = session.run(f"MATCH (n:`{label}`) RETURN count(n) AS cnt").single()
                        node_props[label] = {"properties": props, "count": count_res["cnt"] if count_res else 0}
                    except Exception:
                        node_props[label] = {"properties": {}, "count": 0}
            driver.close()
            return {"database": "neo4j", "labels": node_props,
                    "relationship_types": rel_types}
        except Exception as e:
            return {"database": "neo4j", "error": str(e)}

    def execute_cypher(self, query: str) -> dict:
        """Execute a read-only Cypher query."""
        upper = query.strip().upper()
        BLOCKED = ["CREATE", "DELETE", "DETACH", "SET ", "REMOVE", "MERGE", "DROP"]
        if any(upper.startswith(b) or f" {b}" in upper for b in BLOCKED):
            return {"success": False, "error": "Write operations are blocked"}
        driver = self._get_driver()
        try:
            with driver.session() as session:
                result = session.run(query)
                records = result.data()
                columns = result.keys() if hasattr(result, 'keys') else (list(records[0].keys()) if records else [])
                rows = []
                for rec in records[:500]:
                    row = {}
                    for k, v in rec.items():
                        if hasattr(v, 'items'):
                            row[k] = dict(v)
                        elif hasattr(v, '__iter__') and not isinstance(v, str):
                            row[k] = list(v)
                        else:
                            row[k] = v
                    rows.append(row)
                return {"success": True, "rows": rows, "columns": list(columns),
                        "row_count": len(rows)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            driver.close()


# ── Factory ─────────────────────────────────────────────

def get_nosql_handler(db_type: str, **kwargs):
    """Factory to get the right NoSQL handler."""
    dt = db_type.lower()
    if dt in ("mongodb", "mongo"):
        return MongoHandler(uri=kwargs.get("uri", ""), database=kwargs.get("database", ""))
    elif dt == "redis":
        return RedisHandler(url=kwargs.get("uri", kwargs.get("url", "")))
    elif dt in ("elasticsearch", "elastic", "es"):
        return ElasticsearchHandler(url=kwargs.get("uri", kwargs.get("url", "")),
                                     api_key=kwargs.get("api_key", ""))
    elif dt == "neo4j":
        return Neo4jHandler(uri=kwargs.get("uri", ""),
                             username=kwargs.get("username", "neo4j"),
                             password=kwargs.get("password", ""))
    else:
        raise ValueError(f"Unknown NoSQL type: {db_type}")
