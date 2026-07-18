import os
import json
import re
import pandas as pd
import numpy as np
from flask import current_app
from src.services.db_service import update_pipeline_stage, log_activity, Dataset, db
from src.utils.logger import pipeline_logger, error_logger

# Friendly rename map applied after column names are standardized to snake_case.
# Keys are the standardized snake_case names; values are the final business-facing names.
COLUMN_RENAME_MAP = {
    'transaction_id': 'transaction_id',
    'date': 'transaction_date',
    'product_category': 'product_category',
    'units_sold': 'units_sold',
    'unit_price': 'unit_price',
    'revenue': 'revenue',
    'customer_segment': 'customer_segment',
    'region': 'region',
}

# Canonical category normalization map: maps common variants to a single standardized label.
CATEGORY_NORMALIZATION_MAP = {
    'product_category': {
        'electronic': 'Electronics', 'electronics': 'Electronics',
        'office supply': 'Office Supplies', 'office supplies': 'Office Supplies',
        'furniture': 'Furniture',
    },
    'customer_segment': {
        'consumer': 'Consumer', 'corporate': 'Corporate',
        'home office': 'Home Office', 'homeoffice': 'Home Office',
    },
    'region': {
        'north': 'North', 'south': 'South', 'east': 'East', 'west': 'West',
    }
}


def _standardize_column_name(col: str) -> str:
    """Converts a column name to lower_snake_case."""
    col = col.strip()
    col = re.sub(r'[\s\-]+', '_', col)
    col = re.sub(r'[^0-9a-zA-Z_]', '', col)
    return col.lower()


def transform_dataset(dataset_uuid: str) -> dict:
    """Applies standardized business transformations to the cleaned dataset.

    Steps performed:
        1. Standardize column names to snake_case, then apply a business rename map.
        2. Create calculated columns (revenue-per-unit, calculated revenue check).
        3. Apply currency formatting to price/revenue columns.
        4. Compute each row's percentage share of total revenue.
        5. Extract date features (year, month, month name, quarter, day of week).
        6. Normalize category-like text columns to canonical labels.
        7. Save the transformed dataset and a JSON transformation summary.
    """
    update_pipeline_stage(dataset_uuid, 'Transformation', 'Running')

    try:
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")

        source_path = dataset.cleaned_filepath
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("Cleaned dataset not found. Run the Cleaning stage first.")

        df = pd.read_csv(source_path)
        original_columns = list(df.columns)
        transformations_applied = []

        # 1. Standardize column names, then apply business rename map
        rename_map = {}
        for col in df.columns:
            standardized = _standardize_column_name(col)
            final_name = COLUMN_RENAME_MAP.get(standardized, standardized)
            rename_map[col] = final_name
        df.rename(columns=rename_map, inplace=True)
        transformations_applied.append("Standardized column names to snake_case")
        transformations_applied.append("Applied business-friendly column renaming")

        # 2. Create calculated columns
        if 'units_sold' in df.columns and 'unit_price' in df.columns:
            df['units_sold'] = pd.to_numeric(df['units_sold'], errors='coerce').fillna(0)
            df['unit_price'] = pd.to_numeric(df['unit_price'], errors='coerce').fillna(0)
            df['calculated_revenue'] = (df['units_sold'] * df['unit_price']).round(2)
            transformations_applied.append("Created 'calculated_revenue' (units_sold x unit_price)")

        if 'revenue' in df.columns and 'units_sold' in df.columns:
            df['revenue'] = pd.to_numeric(df['revenue'], errors='coerce').fillna(0)
            df['revenue_per_unit'] = np.where(
                df['units_sold'] != 0, (df['revenue'] / df['units_sold']).round(2), 0.0
            )
            transformations_applied.append("Created 'revenue_per_unit' (revenue / units_sold)")

        # 3. Currency formatting (new formatted string columns, originals preserved for calculations)
        for col in ['unit_price', 'revenue']:
            if col in df.columns:
                formatted_col = f"{col}_formatted"
                df[formatted_col] = df[col].apply(lambda v: f"${v:,.2f}" if pd.notnull(v) else "")
                transformations_applied.append(f"Added currency-formatted column '{formatted_col}'")

        # 4. Percentage calculations: each row's share of total revenue
        if 'revenue' in df.columns:
            total_revenue = df['revenue'].sum()
            if total_revenue and total_revenue != 0:
                df['revenue_pct_of_total'] = (df['revenue'] / total_revenue * 100).round(2)
            else:
                df['revenue_pct_of_total'] = 0.0
            transformations_applied.append("Calculated 'revenue_pct_of_total' (% share of total revenue)")

        # 5. Date feature extraction
        date_col = 'transaction_date' if 'transaction_date' in df.columns else ('date' if 'date' in df.columns else None)
        if date_col:
            parsed_dates = pd.to_datetime(df[date_col], errors='coerce')
            df['year'] = parsed_dates.dt.year
            df['month'] = parsed_dates.dt.month
            df['month_name'] = parsed_dates.dt.month_name()
            df['quarter'] = 'Q' + parsed_dates.dt.quarter.astype('Int64').astype(str)
            df['day_of_week'] = parsed_dates.dt.day_name()
            transformations_applied.append(
                f"Extracted date features (year, month, month_name, quarter, day_of_week) from '{date_col}'"
            )

        # 6. Category normalization for known categorical columns
        normalized_columns = []
        for col, mapping in CATEGORY_NORMALIZATION_MAP.items():
            if col in df.columns:
                def _normalize(val):
                    if pd.isnull(val):
                        return val
                    key = str(val).strip().lower()
                    return mapping.get(key, str(val).strip())
                df[col] = df[col].apply(_normalize)
                normalized_columns.append(col)
        if normalized_columns:
            transformations_applied.append(f"Normalized category labels for: {', '.join(normalized_columns)}")

        new_columns = [c for c in df.columns if c not in original_columns and c not in rename_map.values()]
        final_columns = list(df.columns)

        # 7. Save transformed dataset to uploads/transformed/<uuid>/
        transformed_dir = os.path.join(current_app.config['UPLOAD_TRANSFORMED_DIR'], dataset_uuid)
        os.makedirs(transformed_dir, exist_ok=True)
        transformed_path = os.path.join(transformed_dir, dataset.original_filename)
        df.to_csv(transformed_path, index=False)

        dataset.transformed_filepath = transformed_path
        db.session.commit()

        preview_rows = df.head(10).fillna("").to_dict(orient='records')

        summary = {
            'original_columns': original_columns,
            'renamed_columns': rename_map,
            'new_columns': new_columns,
            'final_columns': final_columns,
            'transformations_applied': transformations_applied,
            'row_count': len(df),
            'preview_headers': final_columns,
            'preview_rows': preview_rows,
            'transformed_filepath': transformed_path
        }

        summary_path = os.path.join(transformed_dir, 'transformation_summary.json')
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=4, default=str)

        update_pipeline_stage(dataset_uuid, 'Transformation', 'Completed')

        log_msg = f"Data transformation completed. {len(new_columns)} new column(s) created, {len(final_columns)} total columns."
        pipeline_logger.info(log_msg)
        log_activity(log_msg, level='INFO', dataset_id=dataset.id, stage='Transformation')

        return summary
    except Exception as e:
        error_msg = f"Fatal data transformation failure: {str(e)}"
        error_logger.error(error_msg)
        update_pipeline_stage(dataset_uuid, 'Transformation', 'Failed', error_message=error_msg)
        raise e
