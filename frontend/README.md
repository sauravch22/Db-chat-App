# DbChat Frontend

Interactive web interface for DbChat - connecting natural language queries with SQL generation and multi-chart visualization.

## Features

✨ **Query Generation**
- Natural language to SQL conversion
- Real-time SQL display
- Copy SQL to clipboard

📊 **Result Visualization**
- Automatic multi-chart generation
- 7+ different chart types
- Feature-based analysis
- Statistical insights

🎯 **Interactive Dashboard**
- Tab-based interface
- Live configuration
- Result summary
- Raw data view

## Architecture

```
Frontend (Port 3000)
    ↓
    ├→ Chat Service (Port 8000) - SQL Generation
    └→ Viz Service (Port 8001) - Visualization
```

## Running the Frontend

### Quick Start

```bash
cd frontend
chmod +x start.sh
./start.sh
```

The frontend will be available at **http://localhost:3000**

### Manual Start

```bash
source ../venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 3000 --reload
```

## Configuration

On the frontend, you can configure:
- **Connection ID**: Database connection identifier (default: 3)
- **Chat Service**: URL of the chat/SQL generation service (default: http://localhost:8000)
- **Viz Service**: URL of the visualization service (default: http://localhost:8001)

## Usage Workflow

### Step 1: Enter Natural Language Query
```
"Show me sales by month"
"Get top customers by total purchases"
"List all products with inventory below 100"
```

### Step 2: Generate SQL
Click "Generate SQL" button
- Displays the generated SQL
- Shows query metadata

### Step 3: Execute & Visualize
Click "Execute Query & Visualize" button
- Executes the SQL query
- Sends results to visualization service
- Generates 7+ chart recommendations

### Step 4: View Results
- **SQL Tab**: View SQL, summary, and raw results
- **Visualization Tab**: Interactive charts with statistics

## Chart Types

The viz service automatically generates:

1. **Distribution Analysis** - Statistical overview
2. **Category Breakdown** - Compare across categories
3. **Top/Bottom Analysis** - Highlight extremes
4. **Composition** - Percentage contribution (pie)
5. **Relationship** - Correlation between columns
6. **Trend Analysis** - Time series trends
7. **Data Table** - Raw data exploration

## API Integration

### Chat Service Endpoints

**Generate SQL**
```
POST /api/chat
{
  "connection_id": 3,
  "prompt": "Show me sales by month"
}
```

**Execute Query**
```
POST /api/execute
{
  "connection_id": 3,
  "sql": "SELECT * FROM users"
}
```

### Viz Service Endpoints

**Analyze & Get Recommendations**
```
POST /analyze
{
  "data": {
    "columns": [{"name": "month", "type": "VARCHAR"}],
    "rows": [{"month": "Jan"}, ...]
  },
  "max_recommendations": 10
}
```

## Technologies Used

- **Frontend**: HTML5, Tailwind CSS, Vanilla JavaScript
- **Charts**: Chart.js, Vega-Lite (ready for upgrade)
- **Server**: FastAPI, Uvicorn
- **CORS**: Enabled for all services

## File Structure

```
frontend/
├── index.html       # Main UI
├── app.js          # Frontend logic
├── server.py       # FastAPI server
├── start.sh        # Startup script
└── README.md       # This file
```

## Troubleshooting

### Port Already in Use
```bash
lsof -i :3000 | grep -v COMMAND | awk '{print $2}' | xargs kill -9
```

### CORS Issues
- Ensure backend services have CORS enabled
- Check that service URLs are correct
- Verify all services are running

### No Charts Appearing
1. Check browser console (F12) for JavaScript errors
2. Verify viz service is running
3. Check that query returns data

## Future Enhancements

- 🔐 Authentication
- 💾 Query history
- 🔄 Saved queries
- 📥 CSV/JSON export
- 🎨 Custom themes
- 📱 Mobile responsive improvements
- 🤖 Query suggestions
- 📊 Advanced Vega-Lite integration

## Support

For issues or questions:
1. Check service logs
2. Verify all services are running
3. Check browser console for errors
4. Review backend error logs
