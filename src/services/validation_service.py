import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from src.services.db_service import update_pipeline_stage, log_activity, Dataset
from src.utils.logger import pipeline_logger, error_logger

# Define default schema for DA Automation System (DAAS) transaction data validation
EXPECTED_SCHEMA = {
    'Date': {
        'type': 'datetime',
        'required': False
    },
    'Revenue': {
        'type': 'numeric',
        'required': False
    }
}

def validate_dataset_schema(dataset_uuid: str) -> dict:
    """Runs complete automated schema, data type, integrity, and duplicate checks on raw CSV."""
    # Register stage as running
    update_pipeline_stage(dataset_uuid, 'Validation', 'Running')

    try:
        # Retrieve dataset metadata from DB
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")

        file_path = dataset.raw_filepath
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Raw data file not found at {file_path}")

        df = pd.read_csv(file_path)

        validation_errors = []
        validation_warnings = []

        present_cols = list(df.columns)

        missing_required = []

        # Generic validation

        if df.empty:
            validation_errors.append("Dataset is empty.")

        if len(present_cols) == 0:
            validation_errors.append("No columns found.")

        duplicate_headers = [
            col for col in present_cols
            if present_cols.count(col) > 1
        ]

        if duplicate_headers:
            validation_errors.append(
                "Duplicate column names found."
            )

        empty_headers = [
            col for col in present_cols
            if str(col).strip() == ""
        ]

        if empty_headers:
            validation_errors.append(
                "Dataset contains empty column names."
            )

        # 2. Check for duplicate rows
        duplicate_details = []

        duplicate_rows = int(df.duplicated().sum())

        if duplicate_rows > 0:
            validation_warnings.append(
                f"{duplicate_rows} duplicate rows found."
            )

        # 3. Detect null values in required fields or general fields
        null_counts = {}
        for col in present_cols:
            null_cnt = int(df[col].isnull().sum())
            if null_cnt > 0:
                null_counts[col] = null_cnt
                if col in EXPECTED_SCHEMA and EXPECTED_SCHEMA[col]['required']:
                    validation_warnings.append(f"Required column '{col}' contains {null_cnt} missing values (nulls).")
                else:
                    validation_warnings.append(f"Column '{col}' contains {null_cnt} missing values.")

        # 4. Check for invalid datatypes (inferred, not schema-enforced)
        invalid_types = {}
        for col in present_cols:
            if pd.api.types.is_numeric_dtype(df[col]):
                continue

            if pd.api.types.is_datetime64_any_dtype(df[col]):
                continue

            non_null_series = df[col].dropna()
            if non_null_series.empty:
                continue

            # Try to infer whether this column is "meant" to be numeric or
            # datetime by seeing how much of it converts cleanly. If a
            # majority of values convert, treat the rest as invalid entries
            # worth flagging rather than assuming the column is just text.
            numeric_converted = pd.to_numeric(non_null_series, errors='coerce')
            numeric_valid_ratio = numeric_converted.notnull().mean()

            datetime_converted = pd.to_datetime(non_null_series, errors='coerce')
            datetime_valid_ratio = datetime_converted.notnull().mean()

            if numeric_valid_ratio > 0.5:
                bad_idx = non_null_series.index[numeric_converted.isnull()]
                bad_rows = [
                    {'row': int(idx + 2), 'value': str(non_null_series.loc[idx])}
                    for idx in bad_idx
                ]
                if bad_rows:
                    invalid_types[col] = bad_rows[:10]  # Store up to 10 sample errors
                    validation_warnings.append(f"Column '{col}' has {len(bad_rows)} non-numeric values.")

            elif datetime_valid_ratio > 0.5:
                bad_idx = non_null_series.index[datetime_converted.isnull()]
                bad_rows = [
                    {'row': int(idx + 2), 'value': str(non_null_series.loc[idx])}
                    for idx in bad_idx
                ]
                if bad_rows:
                    invalid_types[col] = bad_rows[:10]
                    validation_warnings.append(f"Column '{col}' has {len(bad_rows)} invalid date formats.")

        # Determine overall result status
        status = 'Failed' if validation_errors else 'Completed'
        error_msg = validation_errors[0] if validation_errors else None

        # Save summary report as JSON in dataset directory
        summary = {
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'dataset_uuid': dataset_uuid,
            'status': status,
            'missing_required_columns': missing_required,
            'duplicate_id_details': duplicate_details,
            'null_counts': null_counts,
            'invalid_types': invalid_types,
            'errors': validation_errors,
            'warnings': validation_warnings
        }

        summary["rows"] = len(df)
        summary["columns"] = len(df.columns)
        summary["duplicate_rows"] = duplicate_rows
        summary["missing_values"] = int(df.isnull().sum().sum())

        summary["numeric_columns"] = list(
            df.select_dtypes(include="number").columns
        )

        summary["categorical_columns"] = list(
            df.select_dtypes(exclude="number").columns
        )

        summary_dir = os.path.dirname(file_path)
        summary_path = os.path.join(summary_dir, 'validation_summary.json')
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=4)

        update_pipeline_stage(dataset_uuid, 'Validation', status, error_message=error_msg)

        log_activity(
            f"Schema validation completed with status: {status}. Errors: {len(validation_errors)}, Warnings: {len(validation_warnings)}",
            level='ERROR' if status == 'Failed' else 'INFO',
            dataset_id=dataset.id,
            stage='Validation'
        )

        return summary
    except Exception as e:
        error_msg = f"Fatal validation failure: {str(e)}"
        error_logger.error(error_msg)
        update_pipeline_stage(dataset_uuid, 'Validation', 'Failed', error_message=error_msg)
        raise e