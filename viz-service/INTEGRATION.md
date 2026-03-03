# Integration Guide: Chat Service + Viz Service

## Architecture Flow

```
1. User asks question
2. Chat Service (8000) generates SQL
3. Chat Service executes query
4. Chat Service uploads results to S3 → gets signed URL (1hr expiry)
5. Chat Service returns: {sql, s3_url, row_count} to frontend
6. Frontend calls Viz Service (8001) with s3_url
7. Viz Service analyzes data → returns chart recommendations
8. Frontend renders charts using ECharts
```

## Step 1: Add S3 Upload to Chat Service

```python
# app/services/s3_service.py (NEW FILE)
import boto3
import json
from datetime import datetime, timedelta

class S3Service:
    def __init__(self):
        self.s3 = boto3.client('s3')
        self.bucket = "dbchat-results"
    
    def upload_results(self, connection_id: int, query_id: str, data: dict) -> str:
        """Upload query results to S3 and return signed URL"""
        key = f"results/{connection_id}/{query_id}.json"
        
        # Upload to S3
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(data),
            ContentType='application/json'
        )
        
        # Generate signed URL (1 hour expiry)
        url = self.s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': key},
            ExpiresIn=3600  # 1 hour
        )
        
        return url
```

## Step 2: Modify Chat Service Response

```python
# app/services/chat_service.py

from app.services.s3_service import S3Service
import uuid

class ChatService:
    def __init__(self):
        # ... existing code ...
        self.s3 = S3Service()
    
    async def process_query(self, ...):
        # ... execute query ...
        
        # Upload results to S3
        query_id = str(uuid.uuid4())
        result_data = {
            "columns": columns,
            "rows": rows,
            "executed_at": datetime.utcnow().isoformat()
        }
        
        s3_url = self.s3.upload_results(connection_id, query_id, result_data)
        
        return {
            "status": "success",
            "sql": sql,
            "row_count": len(rows),
            "columns": columns[:5],  # First 5 columns for preview
            "rows": rows[:10],  # First 10 rows for preview
            "data_url": s3_url,  # NEW: S3 URL for full data
            "execution_time_ms": ...,
        }
```

## Step 3: Frontend Integration

```javascript
// Frontend calls Chat Service
const chatResponse = await fetch('http://localhost:8000/api/chat', {
  method: 'POST',
  body: JSON.stringify({
    connection_id: 3,
    prompt: "Show revenue by country"
  })
});

const result = await chatResponse.json();

// Show preview data in table
showPreviewTable(result.rows, result.columns);

// If user wants charts, call Viz Service
const vizResponse = await fetch('http://localhost:8001/analyze', {
  method: 'POST',
  body: JSON.stringify({
    data_url: result.data_url,  // S3 URL from chat service
    max_recommendations: 3
  })
});

const vizResult = await vizResponse.json();

// Render recommended charts
vizResult.recommendations.forEach(chart => {
  renderChart(chart.chart_type, chart.config, result.data_url);
});
```

## Step 4: Environment Variables

```bash
# .env for Chat Service
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-east-1
S3_RESULTS_BUCKET=dbchat-results

# No env vars needed for Viz Service (stateless)
```

## Step 5: Deploy Both Services

```bash
# Terminal 1: Chat Service
cd /Users/sauravchakraborty/DbChat
uvicorn serve:app --host 0.0.0.0 --port 8000

# Terminal 2: Viz Service
cd /Users/sauravchakraborty/DbChat/viz-service
uvicorn app:app --host 0.0.0.0 --port 8001
```

Or with Docker:
```bash
# Start both services
docker-compose -f docker-compose.yml up -d  # Chat service
docker-compose -f viz-service/docker-compose.yml up -d  # Viz service
```

## Step 6: Test End-to-End

```bash
# 1. Execute query (Chat Service)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"connection_id": 3, "prompt": "Show revenue by country"}' \
  | jq -r '.data_url' > /tmp/s3_url.txt

# 2. Get chart recommendations (Viz Service)
S3_URL=$(cat /tmp/s3_url.txt)
curl -X POST http://localhost:8001/analyze \
  -H "Content-Type: application/json" \
  -d "{\"data_url\": \"$S3_URL\", \"max_recommendations\": 3}" \
  | jq '.recommendations[].chart_type'
```

## Benefits of This Architecture

✅ **Independent Scaling**: Scale chat and viz services separately  
✅ **Cost Efficient**: S3 storage cheaper than keeping data in memory  
✅ **Stateless**: Both services can scale horizontally  
✅ **Flexible**: Frontend can request different chart types without re-querying DB  
✅ **Cacheable**: Same S3 URL can be used for 1 hour  

## Performance Characteristics

| Service | Latency | Throughput |
|---------|---------|------------|
| Chat (SQL gen) | 2-5s | 10 req/sec/instance |
| S3 Upload | 100-200ms | 1000 req/sec |
| Viz Analysis | 50-100ms | 1000 req/sec/instance |
| Total E2E | ~3-6s | Limited by SQL generation |

## Monitoring

```python
# Add metrics to both services
from prometheus_client import Counter, Histogram

viz_requests = Counter('viz_requests_total', 'Total viz requests')
viz_latency = Histogram('viz_latency_seconds', 'Viz service latency')

@app.post("/analyze")
async def analyze_data(request: AnalyzeRequest):
    viz_requests.inc()
    with viz_latency.time():
        # ... analysis logic ...
```

## Next Steps

1. Set up S3 bucket with lifecycle policy (delete after 24h)
2. Add error handling for expired URLs
3. Implement result caching (Redis) for frequently accessed results
4. Add authentication/authorization
5. Monitor S3 costs and optimize
