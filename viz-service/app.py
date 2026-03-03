"""
Visualization Recommendation Service
Using Lux library for automatic chart recommendation
Runs independently from main chat service
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import List, Dict, Any, Optional
import httpx
import logging
from datetime import datetime
import pandas as pd
import lux

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DbChat Visualization Service",
    description="Microservice for automatic chart recommendation using Lux",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    """Request to analyze data and get chart recommendations"""
    data_url: Optional[HttpUrl] = None  # S3 signed URL
    data: Optional[Dict[str, Any]] = None  # Or direct data payload
    max_recommendations: int = 3


class ChartRecommendation(BaseModel):
    """Single chart recommendation"""
    chart_type: str
    title: str
    priority: int  # 1 = best, 2 = good alternative, 3 = optional
    config: Dict[str, Any]
    reason: str


class AnalyzeResponse(BaseModel):
    """Response with multiple chart recommendations"""
    status: str
    recommendations: List[ChartRecommendation]
    data_summary: Dict[str, Any]
    analyzed_at: str


@app.get("/")
async def root():
    return {
        "service": "DbChat Visualization Service",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_data(request: AnalyzeRequest):
    """
    Analyze query results using Lux and return chart recommendations
    
    Lux automatically generates optimal visualizations based on data
    """
    try:
        # Fetch data from S3 if URL provided
        if request.data_url:
            logger.info(f"Fetching data from: {request.data_url}")
            async with httpx.AsyncClient() as client:
                response = await client.get(str(request.data_url), timeout=10.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=400, detail="Failed to fetch data from URL")
                data = response.json()
        elif request.data:
            data = request.data
        else:
            raise HTTPException(status_code=400, detail="Either data_url or data must be provided")
        
        # Extract columns and rows
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        
        if not columns or not rows:
            raise HTTPException(status_code=400, detail="Data must contain columns and rows")
        
        logger.info(f"Analyzing {len(columns)} columns, {len(rows)} rows")
        
        # Convert to pandas DataFrame
        df = pd.DataFrame(rows)
        
        # Infer data types from PostgreSQL column info
        for col_info in columns:
            col_name = col_info.get('name')
            col_type = col_info.get('type', '').upper()
            
            if col_name in df.columns:
                # Convert based on PostgreSQL type
                if 'INT' in col_type or 'NUMERIC' in col_type or 'DECIMAL' in col_type:
                    df[col_name] = pd.to_numeric(df[col_name], errors='coerce')
                elif 'TIMESTAMP' in col_type or 'DATE' in col_type:
                    df[col_name] = pd.to_datetime(df[col_name], errors='coerce')
                elif 'BOOL' in col_type:
                    df[col_name] = df[col_name].astype('category')
        
        # Generate recommendations using Lux
        # Lux automatically creates visualizations
        recommendations = generate_lux_recommendations(df, max_count=request.max_recommendations)
        
        # Generate summary
        analysis = {
            "column_count": len(columns),
            "row_count": len(rows),
            "numeric_columns": df.select_dtypes(include=['number']).columns.tolist(),
            "category_columns": df.select_dtypes(include=['object', 'category']).columns.tolist(),
            "time_columns": df.select_dtypes(include=['datetime']).columns.tolist(),
        }
        
        return AnalyzeResponse(
            status="success",
            recommendations=recommendations,
            data_summary=analysis,
            analyzed_at=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def generate_lux_recommendations(df: pd.DataFrame, max_count: int = 3) -> List[ChartRecommendation]:
    """
    Extract important features from data and generate multiple charts
    
    Analyzes patterns, trends, distributions, and creates visualizations
    to highlight different aspects of the data
    """
    recommendations = []
    
    try:
        # Analyze columns
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        category_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        time_cols = df.select_dtypes(include=['datetime']).columns.tolist()
        
        # Extract features and create targeted charts
        
        # Feature 1: Distribution Analysis (histogram/bar for numeric)
        if numeric_cols:
            col = numeric_cols[0]
            stats = {
                "mean": float(df[col].mean()),
                "median": float(df[col].median()),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "std": float(df[col].std())
            }
            
            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"Distribution Analysis: {col.replace('_', ' ').title()}",
                priority=1,
                config={
                    "data": df.to_dict('records'),
                    "y_field": col,
                    "statistics": stats,
                    "description": f"Range: {stats['min']:.0f} - {stats['max']:.0f}, Mean: {stats['mean']:.1f}"
                },
                reason=f"Shows distribution and key statistics (mean={stats['mean']:.1f}, range={stats['min']:.0f}-{stats['max']:.0f})"
            ))
        
        # Feature 2: Category Breakdown (if categories exist with numeric)
        if category_cols and numeric_cols:
            cat_col = category_cols[0]
            num_col = numeric_cols[0]
            
            # Calculate aggregates by category
            category_stats = df.groupby(cat_col)[num_col].agg(['sum', 'mean', 'count']).to_dict()
            
            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"{num_col.replace('_', ' ').title()} by {cat_col.replace('_', ' ').title()}",
                priority=1,
                config={
                    "data": df.to_dict('records'),
                    "x_field": cat_col,
                    "y_field": num_col,
                    "aggregation": "sum",
                    "category_count": len(df[cat_col].unique())
                },
                reason=f"Compare {num_col} across {len(df[cat_col].unique())} {cat_col} categories"
            ))
        
        # Feature 3: Trend Analysis (if time series data)
        if time_cols and numeric_cols:
            time_col = time_cols[0]
            num_col = numeric_cols[0]
            
            # Calculate trend
            sorted_df = df.sort_values(time_col)
            values = sorted_df[num_col].values
            trend = "increasing" if len(values) > 1 and values[-1] > values[0] else "decreasing"
            trend_pct = abs((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0
            
            recommendations.append(ChartRecommendation(
                chart_type="line",
                title=f"Trend: {num_col.replace('_', ' ').title()} Over Time",
                priority=1,
                config={
                    "data": df.to_dict('records'),
                    "x_field": time_col,
                    "y_field": num_col,
                    "trend": trend,
                    "trend_percentage": trend_pct
                },
                reason=f"Time series showing {trend} trend ({trend_pct:.1f}% change)"
            ))
        
        # Feature 4: Top/Bottom Analysis (for numeric with many rows)
        if numeric_cols and len(df) > 5 and category_cols:
            num_col = numeric_cols[0]
            cat_col = category_cols[0]
            
            top_values = df.nlargest(3, num_col)
            bottom_values = df.nsmallest(3, num_col)
            
            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"Top vs Bottom {cat_col.replace('_', ' ').title()}",
                priority=2,
                config={
                    "data": pd.concat([top_values, bottom_values]).to_dict('records'),
                    "x_field": cat_col,
                    "y_field": num_col,
                    "highlight_top": 3,
                    "highlight_bottom": 3
                },
                reason=f"Highlights {top_values[num_col].max():.0f} (highest) vs {bottom_values[num_col].min():.0f} (lowest)"
            ))
        
        # Feature 5: Correlation/Relationship (if multiple numeric columns)
        if len(numeric_cols) >= 2:
            x_col = numeric_cols[0]
            y_col = numeric_cols[1]
            corr = df[[x_col, y_col]].corr().iloc[0, 1]
            
            recommendations.append(ChartRecommendation(
                chart_type="scatter",
                title=f"Relationship: {x_col} vs {y_col}",
                priority=2,
                config={
                    "data": df.to_dict('records'),
                    "x_field": x_col,
                    "y_field": y_col,
                    "correlation": float(corr)
                },
                reason=f"Shows correlation ({corr:.2f}) between {x_col} and {y_col}"
            ))
        
        # Feature 6: Composition Analysis (pie for categories)
        if category_cols and numeric_cols and len(df) <= 10:
            recommendations.append(ChartRecommendation(
                chart_type="pie",
                title=f"Composition: {numeric_cols[0].replace('_', ' ').title()} by Category",
                priority=3,
                config={
                    "data": df.to_dict('records'),
                    "value_field": numeric_cols[0],
                    "category_field": category_cols[0],
                    "total": float(df[numeric_cols[0]].sum())
                },
                reason="Shows what percentage each category contributes to the total"
            ))
        
        # Feature 7: Raw Data Table
        recommendations.append(ChartRecommendation(
            chart_type="table",
            title="Detailed Data",
            priority=4,
            config={
                "data": df.head(50).to_dict('records'),
                "columns": df.columns.tolist(),
                "row_count": len(df),
                "show_pagination": len(df) > 20
            },
            reason="Full dataset for detailed exploration"
        ))
    
    except Exception as e:
        logger.error(f"Error analyzing data: {str(e)}")
        # Return simple fallback if analysis fails
        recommendations = [
            ChartRecommendation(
                chart_type="table",
                title="Data Table",
                priority=1,
                config={"data": df.to_dict('records')},
                reason="Unable to analyze, showing raw data"
            )
        ]
    
    return recommendations[:max_count]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
