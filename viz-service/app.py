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
        if request.data_url:
            url_str = str(request.data_url)
            import ipaddress, urllib.parse
            parsed = urllib.parse.urlparse(url_str)
            blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal", "169.254.169.254"}
            if parsed.hostname and parsed.hostname.lower() in blocked_hosts:
                raise HTTPException(status_code=400, detail="Fetching from private/internal URLs is not allowed")
            try:
                addr = ipaddress.ip_address(parsed.hostname or "")
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    raise HTTPException(status_code=400, detail="Fetching from private/internal URLs is not allowed")
            except ValueError:
                pass

            logger.info(f"Fetching data from: {request.data_url}")
            async with httpx.AsyncClient() as client:
                response = await client.get(url_str, timeout=10.0)
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


def _is_id_column(col_name: str, df: pd.DataFrame) -> bool:
    """
    Detect if a column is an auto-increment ID or foreign key field.
    These should NEVER be plotted on a value (y) axis.
    """
    name_lower = col_name.lower().strip()

    # ── Name-based: common ID patterns ──────────────────────
    if name_lower == 'id' or name_lower.endswith('_id'):
        return True

    # ── Value-based: sequential unique integers (auto-increment) ──
    if col_name in df.columns and df[col_name].dtype in ['int64', 'float64', 'Int64']:
        vals = df[col_name].dropna()
        n = len(vals)
        if n > 3 and vals.nunique() == n:
            sorted_vals = sorted(vals)
            # Check first ~20 diffs for sequential pattern
            check_len = min(len(sorted_vals) - 1, 20)
            diffs = [sorted_vals[i + 1] - sorted_vals[i] for i in range(check_len)]
            if all(d == 1 for d in diffs):
                return True

    return False


def _pick_measure_columns(numeric_cols: list, id_cols: list) -> list:
    """
    Return numeric columns sorted by usefulness as a chart measure.
    ID columns are excluded entirely.
    """
    measures = [c for c in numeric_cols if c not in id_cols]

    # Columns whose names suggest real values come first
    priority_keywords = [
        'revenue', 'total', 'sum', 'count', 'amount', 'sales', 'price',
        'quantity', 'profit', 'cost', 'avg', 'average', 'score', 'rating',
        'num', 'number', 'balance', 'income', 'expense', 'fee', 'tax',
        'discount', 'weight', 'height', 'size', 'length', 'duration',
        'age', 'salary', 'wage', 'rate', 'percent', 'ratio',
    ]

    def priority(col):
        low = col.lower()
        for i, kw in enumerate(priority_keywords):
            if kw in low:
                return i
        return len(priority_keywords)

    measures.sort(key=priority)
    return measures


def _pick_label_column(category_cols: list, id_cols: list, df: pd.DataFrame) -> Optional[str]:
    """Pick the best column for chart labels / x-axis."""
    if not category_cols and not id_cols:
        return None

    if category_cols:
        # Prefer name / title / label columns
        for kw in ['name', 'title', 'label', 'description', 'category', 'type', 'status']:
            for col in category_cols:
                if kw in col.lower():
                    return col
        return category_cols[0]

    # Fallback: stringify an ID column (useful as a row identifier, not a measure)
    return id_cols[0] if id_cols else None


def _pretty(col_name: str) -> str:
    """'total_revenue' → 'Total Revenue'"""
    return col_name.replace('_', ' ').title()


def generate_lux_recommendations(df: pd.DataFrame, max_count: int = 3) -> List[ChartRecommendation]:
    """
    Generate smart chart recommendations.

    Key principle: auto-increment / foreign-key ID columns are NEVER used as
    the value (y) axis.  They may appear as labels when no better text column
    exists.
    """
    recommendations = []

    try:
        # ── Column classification ──────────────────────────────
        all_numeric = df.select_dtypes(include=['number']).columns.tolist()
        category_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        time_cols = df.select_dtypes(include=['datetime']).columns.tolist()

        id_cols = [c for c in all_numeric if _is_id_column(c, df)]
        measure_cols = _pick_measure_columns(all_numeric, id_cols)
        label_col = _pick_label_column(category_cols, id_cols, df)

        logger.info(
            f"Column classification — measures: {measure_cols}, "
            f"ids (excluded from y-axis): {id_cols}, "
            f"categories: {category_cols}, label: {label_col}, time: {time_cols}"
        )

        has_measure = len(measure_cols) > 0

        # ── Feature 1: Main bar chart (measure by label) ──────
        if has_measure and label_col:
            m = measure_cols[0]
            stats = {
                "mean": float(df[m].mean()),
                "median": float(df[m].median()),
                "min": float(df[m].min()),
                "max": float(df[m].max()),
                "std": float(df[m].std()) if len(df) > 1 else 0.0,
            }
            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"{_pretty(m)} by {_pretty(label_col)}",
                priority=1,
                config={
                    "data": df.to_dict('records'),
                    "x_field": label_col,
                    "y_field": m,
                    "statistics": stats,
                    "description": f"Range: {stats['min']:.0f} – {stats['max']:.0f}, Mean: {stats['mean']:.1f}",
                },
                reason=f"Shows {_pretty(m)} across {_pretty(label_col)} "
                       f"(mean={stats['mean']:.1f}, range={stats['min']:.0f}–{stats['max']:.0f})",
            ))

        # ── Feature 1b: Distribution of single measure (no label) ─
        elif has_measure and not label_col:
            m = measure_cols[0]
            stats = {
                "mean": float(df[m].mean()),
                "median": float(df[m].median()),
                "min": float(df[m].min()),
                "max": float(df[m].max()),
                "std": float(df[m].std()) if len(df) > 1 else 0.0,
            }
            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"Distribution: {_pretty(m)}",
                priority=1,
                config={
                    "data": df.to_dict('records'),
                    "y_field": m,
                    "statistics": stats,
                    "description": f"Range: {stats['min']:.0f} – {stats['max']:.0f}, Mean: {stats['mean']:.1f}",
                },
                reason=f"Distribution of {_pretty(m)} (mean={stats['mean']:.1f})",
            ))

        # ── Feature 2: Trend over time ────────────────────────
        if time_cols and has_measure:
            time_col = time_cols[0]
            m = measure_cols[0]
            sorted_df = df.sort_values(time_col)
            values = sorted_df[m].values
            trend = "increasing" if len(values) > 1 and values[-1] > values[0] else "decreasing"
            trend_pct = abs((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0

            recommendations.append(ChartRecommendation(
                chart_type="line",
                title=f"Trend: {_pretty(m)} Over Time",
                priority=1,
                config={
                    "data": df.to_dict('records'),
                    "x_field": time_col,
                    "y_field": m,
                    "trend": trend,
                    "trend_percentage": trend_pct,
                },
                reason=f"Time series showing {trend} trend ({trend_pct:.1f}% change)",
            ))

        # ── Feature 3: Top / Bottom (need label + measure + enough rows)
        if has_measure and label_col and len(df) > 5:
            m = measure_cols[0]
            top = df.nlargest(3, m)
            bottom = df.nsmallest(3, m)
            combined = pd.concat([top, bottom]).drop_duplicates()

            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"Top vs Bottom by {_pretty(m)}",
                priority=2,
                config={
                    "data": combined.to_dict('records'),
                    "x_field": label_col,
                    "y_field": m,
                    "highlight_top": 3,
                    "highlight_bottom": 3,
                },
                reason=f"Highlights highest ({top[m].max():.0f}) vs lowest ({bottom[m].min():.0f})",
            ))

        # ── Feature 4: Scatter / Correlation (need ≥2 measures) ─
        if len(measure_cols) >= 2:
            x_m, y_m = measure_cols[0], measure_cols[1]
            corr = df[[x_m, y_m]].corr().iloc[0, 1]
            recommendations.append(ChartRecommendation(
                chart_type="scatter",
                title=f"{_pretty(x_m)} vs {_pretty(y_m)}",
                priority=2,
                config={
                    "data": df.to_dict('records'),
                    "x_field": x_m,
                    "y_field": y_m,
                    "correlation": float(corr),
                },
                reason=f"Correlation {corr:.2f} between {_pretty(x_m)} and {_pretty(y_m)}",
            ))

        # ── Feature 5: Pie / Composition (small datasets) ─────
        if has_measure and label_col and len(df) <= 10:
            m = measure_cols[0]
            total = float(df[m].sum())
            recommendations.append(ChartRecommendation(
                chart_type="pie",
                title=f"Composition: {_pretty(m)} by {_pretty(label_col)}",
                priority=3,
                config={
                    "data": df.to_dict('records'),
                    "value_field": m,
                    "category_field": label_col,
                    "total": total,
                },
                reason="Shows what percentage each category contributes to the total",
            ))

        # ── Feature 6: Count-based chart (no measure cols at all) ─
        if not has_measure and label_col:
            counts = df[label_col].value_counts().reset_index()
            counts.columns = [label_col, 'count']
            recommendations.append(ChartRecommendation(
                chart_type="bar",
                title=f"Count by {_pretty(label_col)}",
                priority=1,
                config={
                    "data": counts.to_dict('records'),
                    "x_field": label_col,
                    "y_field": "count",
                },
                reason=f"Record count per {_pretty(label_col)} (no numeric measure available)",
            ))

        # ── Always include raw data table ──────────────────────
        recommendations.append(ChartRecommendation(
            chart_type="table",
            title="Detailed Data",
            priority=4,
            config={
                "data": df.head(50).to_dict('records'),
                "columns": df.columns.tolist(),
                "row_count": len(df),
                "show_pagination": len(df) > 20,
            },
            reason="Full dataset for detailed exploration",
        ))

    except Exception as e:
        logger.error(f"Error analyzing data: {str(e)}")
        recommendations = [
            ChartRecommendation(
                chart_type="table",
                title="Data Table",
                priority=1,
                config={"data": df.to_dict('records')},
                reason="Unable to analyze, showing raw data",
            )
        ]

    return recommendations[:max_count]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
