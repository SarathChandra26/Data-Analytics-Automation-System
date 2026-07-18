import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from flask import current_app
from src.services.db_service import update_pipeline_stage, log_activity, Dataset, db
from src.utils.logger import pipeline_logger, error_logger

# Candidate column names (in priority order) used to auto-detect key business fields
# regardless of which pipeline stage produced the source file.
REVENUE_COLUMNS = ['revenue', 'calculated_revenue', 'sales', 'total_sales', 'amount']
SALES_COLUMNS = ['units_sold', 'quantity', 'qty', 'sales_units']
CATEGORY_COLUMNS = ['product_category', 'category', 'segment', 'customer_segment']
DATE_COLUMNS = ['transaction_date', 'date', 'order_date']


def _first_match(columns: list, candidates: list):
    """Returns the first candidate column name that exists in `columns` (case-insensitive)."""
    lower_map = {c.lower(): c for c in columns}
    for candidate in candidates:
        if candidate in lower_map:
            return lower_map[candidate]
    return None


def _safe_round(value, digits=2):
    try:
        if value is None or pd.isnull(value):
            return 0
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0


def compute_analytics(df: pd.DataFrame) -> dict:
    """Computes the full suite of business KPIs and summary statistics for a dataframe."""
    row_count = len(df)
    column_count = len(df.columns)

    # Missing value percentage (overall, across all cells)
    total_cells = row_count * column_count if row_count and column_count else 1
    missing_cells = int(df.isnull().sum().sum())
    missing_percentage = _safe_round((missing_cells / total_cells) * 100) if total_cells else 0.0

    revenue_col = _first_match(list(df.columns), REVENUE_COLUMNS)
    sales_col = _first_match(list(df.columns), SALES_COLUMNS)
    category_col = _first_match(list(df.columns), CATEGORY_COLUMNS)
    date_col = _first_match(list(df.columns), DATE_COLUMNS)

    # --- Revenue metrics ---
    revenue_metrics = {'available': False}
    if revenue_col:
        revenue_series = pd.to_numeric(df[revenue_col], errors='coerce').fillna(0)
        revenue_metrics = {
            'available': True,
            'column_used': revenue_col,
            'total_revenue': _safe_round(revenue_series.sum()),
            'average_revenue': _safe_round(revenue_series.mean()),
            'max_revenue': _safe_round(revenue_series.max()),
            'min_revenue': _safe_round(revenue_series.min()),
        }

    # --- Sales / units metrics ---
    sales_metrics = {'available': False}
    if sales_col:
        sales_series = pd.to_numeric(df[sales_col], errors='coerce').fillna(0)
        sales_metrics = {
            'available': True,
            'column_used': sales_col,
            'total_units_sold': _safe_round(sales_series.sum()),
            'average_units_sold': _safe_round(sales_series.mean()),
            'max_units_sold': _safe_round(sales_series.max()),
            'min_units_sold': _safe_round(sales_series.min()),
        }

    # --- Top categories (by revenue if available, else by frequency) ---
    top_categories = []
    if category_col:
        if revenue_col:
            revenue_series = pd.to_numeric(df[revenue_col], errors='coerce').fillna(0)
            grouped = df.assign(_rev=revenue_series).groupby(category_col)['_rev'].sum()
            grouped = grouped.sort_values(ascending=False).head(10)
            total = grouped.sum() or 1
            top_categories = [
                {
                    'category': str(cat),
                    'value': _safe_round(val),
                    'metric': 'revenue',
                    'percentage': _safe_round((val / total) * 100)
                }
                for cat, val in grouped.items()
            ]
        else:
            counts = df[category_col].value_counts().head(10)
            total = counts.sum() or 1
            top_categories = [
                {
                    'category': str(cat),
                    'value': int(val),
                    'metric': 'count',
                    'percentage': _safe_round((val / total) * 100)
                }
                for cat, val in counts.items()
            ]

    # --- Monthly trends ---
    monthly_trends = []
    if date_col:
        parsed_dates = pd.to_datetime(df[date_col], errors='coerce')
        month_period = parsed_dates.dt.to_period('M')
        if revenue_col:
            revenue_series = pd.to_numeric(df[revenue_col], errors='coerce').fillna(0)
            trend_df = pd.DataFrame({'period': month_period, 'value': revenue_series})
            metric_label = 'revenue'
        elif sales_col:
            sales_series = pd.to_numeric(df[sales_col], errors='coerce').fillna(0)
            trend_df = pd.DataFrame({'period': month_period, 'value': sales_series})
            metric_label = 'units_sold'
        else:
            trend_df = pd.DataFrame({'period': month_period, 'value': 1})
            metric_label = 'record_count'

        trend_df = trend_df.dropna(subset=['period'])
        grouped_trend = trend_df.groupby('period')['value'].sum().sort_index()
        monthly_trends = [
            {'month': str(period), 'value': _safe_round(val), 'metric': metric_label}
            for period, val in grouped_trend.items()
        ]

    # --- Summary statistics for all numeric columns ---
    numeric_df = df.select_dtypes(include=[np.number])
    summary_statistics = {}
    for col in numeric_df.columns:
        series = numeric_df[col].dropna()
        if series.empty:
            continue
        summary_statistics[col] = {
            'sum': _safe_round(series.sum()),
            'mean': _safe_round(series.mean()),
            'median': _safe_round(series.median()),
            'std_dev': _safe_round(series.std()) if len(series) > 1 else 0,
            'min': _safe_round(series.min()),
            'max': _safe_round(series.max()),
            'count': int(series.count()),
        }

    return {
        'row_count': row_count,
        'column_count': column_count,
        'missing_percentage': missing_percentage,
        'missing_cells': missing_cells,
        'revenue_metrics': revenue_metrics,
        'sales_metrics': sales_metrics,
        'top_categories': top_categories,
        'category_column_used': category_col,
        'monthly_trends': monthly_trends,
        'date_column_used': date_col,
        'summary_statistics': summary_statistics,
        'numeric_columns': list(numeric_df.columns),
    }


def generate_analytics(dataset_uuid: str) -> dict:
    """Runs the analytics engine against a dataset's processed CSV and persists the results.

    Steps performed:
        1. Load the transformed dataset (falls back to cleaned, then raw).
        2. Compute row/column counts, missing %, revenue/sales KPIs, top categories,
           monthly trends and summary statistics.
        3. Save the results as a JSON file under uploads/analytics/<uuid>/analytics_summary.json.
        4. Track completion via the pipeline stage table and activity log.
    """
    update_pipeline_stage(dataset_uuid, 'Analytics', 'Running')

    try:
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")

        source_path = dataset.transformed_filepath or dataset.cleaned_filepath or dataset.raw_filepath
        source_stage = (
            'Transformation' if dataset.transformed_filepath
            else ('Cleaning' if dataset.cleaned_filepath else 'Upload')
        )
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("No processed dataset available. Run earlier pipeline stages first.")

        df = pd.read_csv(source_path)
        results = compute_analytics(df)
        results['source_filepath'] = source_path
        results['source_stage'] = source_stage
        results['generated_at'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        analytics_base = os.path.join(current_app.config['BASE_DIR'], 'uploads', 'analytics')
        analytics_dir = os.path.join(analytics_base, dataset_uuid)
        os.makedirs(analytics_dir, exist_ok=True)
        summary_path = os.path.join(analytics_dir, 'analytics_summary.json')
        with open(summary_path, 'w') as f:
            json.dump(results, f, indent=4, default=str)

        update_pipeline_stage(dataset_uuid, 'Analytics', 'Completed')

        log_msg = (
            f"Analytics engine computed {len(results['summary_statistics'])} numeric summaries, "
            f"{len(results['top_categories'])} top categories, {len(results['monthly_trends'])} monthly points."
        )
        pipeline_logger.info(log_msg)
        log_activity(log_msg, level='INFO', dataset_id=dataset.id, stage='Analytics')

        return results
    except Exception as e:
        error_msg = f"Fatal analytics engine failure: {str(e)}"
        error_logger.error(error_msg)
        update_pipeline_stage(dataset_uuid, 'Analytics', 'Failed', error_message=error_msg)
        raise e
