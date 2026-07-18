import os
import pandas as pd
import numpy as np
from datetime import datetime
from src.services.db_service import (
    db, Dataset, update_pipeline_stage, log_activity,
    AnalyticsRecord, AnalyticsTableMeta
)
from src.utils.logger import pipeline_logger, error_logger

ANALYTICS_TABLE_NAME = 'analytics_data'

# Maps transformed-dataset column names to AnalyticsRecord model fields.
COLUMN_TO_FIELD_MAP = {
    'transaction_id': 'transaction_id',
    'transaction_date': 'transaction_date',
    'date': 'transaction_date',
    'product_category': 'product_category',
    'units_sold': 'units_sold',
    'unit_price': 'unit_price',
    'revenue': 'revenue',
    'revenue_pct_of_total': 'revenue_percentage_of_total',
    'customer_segment': 'customer_segment',
    'region': 'region',
    'year': 'year',
    'month': 'month',
    'month_name': 'month_name',
    'quarter': 'quarter',
    'day_of_week': 'day_of_week',
}


def _safe_float(val):
    try:
        if pd.isnull(val):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val):
    try:
        if pd.isnull(val):
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def load_dataset_to_database(dataset_uuid: str) -> dict:
    """Imports the processed dataset into the standardized SQLite 'analytics_data' table.

    Steps performed:
        1. Load the transformed dataset (falls back to cleaned dataset if not transformed).
        2. Create/verify the standardized analytics table (via SQLAlchemy models).
        3. Insert records, replacing any prior import for this dataset (idempotent).
        4. Store import metadata (record/column counts, source file, timestamp, status).
        5. Track the import in processing/activity history.
    """
    update_pipeline_stage(dataset_uuid, 'Database', 'Running')

    try:
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")

        # Prefer the transformed dataset; fall back to the cleaned dataset
        source_path = dataset.transformed_filepath or dataset.cleaned_filepath
        source_stage = 'Transformation' if dataset.transformed_filepath else 'Cleaning'
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("No processed dataset available. Run Cleaning/Transformation first.")

        df = pd.read_csv(source_path)
        column_count = len(df.columns)

        # Remove any previously imported records for this dataset (idempotent re-import)
        AnalyticsRecord.query.filter_by(dataset_id=dataset.id).delete()

        records = []
        for _, row in df.iterrows():
            record_kwargs = {'dataset_id': dataset.id}
            for csv_col, field in COLUMN_TO_FIELD_MAP.items():
                if csv_col not in df.columns:
                    continue
                value = row[csv_col]
                if field in ('units_sold', 'unit_price', 'revenue', 'revenue_percentage_of_total'):
                    record_kwargs[field] = _safe_float(value)
                elif field in ('year', 'month'):
                    record_kwargs[field] = _safe_int(value)
                else:
                    record_kwargs[field] = None if pd.isnull(value) else str(value)
            records.append(AnalyticsRecord(**record_kwargs))

        db.session.bulk_save_objects(records)

        # Upsert the analytics table metadata row
        meta = AnalyticsTableMeta.query.filter_by(dataset_id=dataset.id).first()
        if not meta:
            meta = AnalyticsTableMeta(dataset_id=dataset.id)
            db.session.add(meta)

        meta.table_name = ANALYTICS_TABLE_NAME
        meta.record_count = len(records)
        meta.column_count = column_count
        meta.source_filepath = source_path
        meta.imported_at = datetime.utcnow()
        meta.import_status = 'Completed'

        db.session.commit()

        update_pipeline_stage(dataset_uuid, 'Database', 'Completed')

        log_msg = (
            f"Loaded {len(records)} record(s) into '{ANALYTICS_TABLE_NAME}' table "
            f"from {source_stage} output ({column_count} columns)."
        )
        pipeline_logger.info(log_msg)
        log_activity(log_msg, level='INFO', dataset_id=dataset.id, stage='Database')

        return {
            'table_name': ANALYTICS_TABLE_NAME,
            'record_count': len(records),
            'column_count': column_count,
            'source_filepath': source_path,
            'source_stage': source_stage,
            'imported_at': meta.imported_at.strftime('%Y-%m-%d %H:%M:%S'),
            'import_status': meta.import_status
        }
    except Exception as e:
        db.session.rollback()
        error_msg = f"Fatal database load failure: {str(e)}"
        error_logger.error(error_msg)
        update_pipeline_stage(dataset_uuid, 'Database', 'Failed', error_message=error_msg)
        raise e
