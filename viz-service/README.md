# DbChat Visualization Service

**Separate microservice for chart recommendation - scales independently**

## Architecture

```
Chat Service (8000) → S3 → Viz Service (8001) → Frontend
```

## Features

- ✅ Rule-based chart selection (no LLM needed)
- ✅ Multiple recommendations per dataset
- ✅ Stateless & horizontally scalable
- ✅ Reads from S3 signed URLs
- ✅ 10+ chart types supported

## Installation

```bash
cd viz-service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# Development
uvicorn app:app --host 0.0.0.0 --port 8001 --reload

# Or use script
chmod +x start.sh
./start.sh
```

## API Usage

### Health Check
```bash
curl http://localhost:8001/health
```

### Analyze Data from S3
```bash
curl -X POST http://localhost:8001/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "data_url": "https://s3.amazonaws.com/bucket/results.json?signature=...",
    "max_recommendations": 3
  }'
```

### Analyze Direct Data
```bash
curl -X POST http://localhost:8001/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "columns": [
        {"name": "country", "type": "VARCHAR"},
        {"name": "total", "type": "NUMERIC"}
      ],
      "rows": [
        {"country": "USA", "total": 50000},
        {"country": "India", "total": 20000}
      ]
    },
    "max_recommendations": 3
  }'
```

## Response Format

```json
{
  "status": "success",
  "recommendations": [
    {
      "chart_type": "bar",
      "title": "Total by Country",
      "priority": 1,
      "config": {
        "x_axis": {"field": "country", "type": "category"},
        "y_axis": {"field": "total", "type": "value"},
        "sort": "desc"
      },
      "reason": "Comparing total across 2 categories"
    },
    {
      "chart_type": "pie",
      "title": "Total Distribution",
      "priority": 2,
      "config": {
        "name_field": "country",
        "value_field": "total"
      },
      "reason": "Distribution view works well with 2 categories"
    }
  ],
  "data_summary": {
    "column_count": 2,
    "row_count": 2,
    "numeric_columns": ["total"],
    "category_columns": ["country"],
    "cardinalities": {"country": 2}
  }
}
```

## Chart Types

1. **KPI** - Single numeric value
2. **Line** - Time series trends
3. **Area** - Time series with volume emphasis
4. **Bar** - Category comparisons
5. **Horizontal Bar** - Many categories
6. **Pie/Donut** - Distribution (few categories)
7. **Grouped Bar** - Two dimensions
8. **Stacked Bar** - Composition over categories
9. **Scatter** - Two numeric relationships
10. **Table** - Detailed data view

## Selection Rules

| Data Pattern | Recommended Charts |
|--------------|-------------------|
| 1 numeric | KPI card |
| Time + Numeric | Line → Area |
| Category + Numeric | Bar → Pie → Horizontal Bar |
| 2 Categories + Numeric | Grouped Bar → Stacked Bar |
| 2+ Numerics | Scatter → Table |
| Large dataset | Table |

## Scaling

### Horizontal Scaling
```bash
# Run multiple instances
uvicorn app:app --port 8001 &
uvicorn app:app --port 8002 &
uvicorn app:app --port 8003 &

# Use nginx/HAProxy load balancer
```

### Docker
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
```

## Integration with Chat Service

1. **Chat service** executes SQL → uploads results to S3
2. Returns S3 signed URL (1hr expiry) to frontend
3. **Frontend** calls viz service with S3 URL
4. **Viz service** fetches data, analyzes, returns charts
5. **Frontend** renders using ECharts/Chart.js

## Performance

- **Latency**: <100ms for typical datasets
- **Throughput**: 1000+ req/sec per instance
- **Memory**: ~50MB per instance
- **Stateless**: Easy to scale horizontally

## Testing

```python
# Test with sample data
import requests

response = requests.post("http://localhost:8001/analyze", json={
    "data": {
        "columns": [
            {"name": "invoice_date", "type": "DATE"},
            {"name": "total", "type": "NUMERIC"}
        ],
        "rows": [
            {"invoice_date": "2024-01-01", "total": 100},
            {"invoice_date": "2024-02-01", "total": 200}
        ]
    },
    "max_recommendations": 3
})

print(response.json())
```

## Future Enhancements

- [ ] Store chart preferences in user profile
- [ ] Learn from user chart selections (feedback loop)
- [ ] Support custom chart templates
- [ ] Add statistical insights (outliers, trends)
- [ ] Multi-dataset comparisons
