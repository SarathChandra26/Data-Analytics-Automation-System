import os
import json
import pandas as pd
import numpy as np
from flask import current_app
from src.services.db_service import update_pipeline_stage, log_activity, Dataset, db
from src.services.validation_service import EXPECTED_SCHEMA
from src.utils.logger import pipeline_logger, error_logger


def clean_dataset(dataset_uuid: str, casing_rule: str = 'title') -> dict:
    """Executes automated data cleaning on the raw dataset.

    Steps performed:
        1. Remove completely empty rows.
        2. Remove duplicate rows (by primary key when available, else full-row).
        3. Trim whitespace on all text columns.
        4. Normalize text casing (configurable: 'title', 'upper', 'lower', or 'none').
        5. Convert numeric columns safely (coercing invalid values to NaN first).
        6. Standardize date formats to ISO (YYYY-MM-DD).
        7. Handle missing values: numeric -> median, categorical -> mode (fallback 'Unknown').
        8. Save the cleaned dataset and a JSON cleaning summary.
    """
    update_pipeline_stage(dataset_uuid, 'Cleaning', 'Running')

    try:
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")

        raw_path = dataset.raw_filepath
        if not os.path.exists(raw_path):
            raise FileNotFoundError(f"Raw dataset file not found at {raw_path}")

        df = pd.read_csv(raw_path)
        original_rows = len(df)
        original_columns = list(df.columns)

        # 1. Remove completely empty rows (all values NaN/blank)
        df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
        before_empty = len(df)
        df.dropna(how='all', inplace=True)
        empty_rows_removed = before_empty - len(df)

        # 2. Remove duplicate rows based on primary key Transaction_ID (if present)
        id_col = next((col for col, rules in EXPECTED_SCHEMA.items() if rules.get('unique')), None)
        before_dups = len(df)
        if id_col and id_col in df.columns:
            df.drop_duplicates(subset=[id_col], keep='first', inplace=True)
        else:
            df.drop_duplicates(inplace=True)
        duplicates_removed = before_dups - len(df)

        # 3 & 4. Trim whitespace and normalize text casing on object columns
        text_columns_cleaned = []
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.strip()
                df[col] = df[col].replace({'nan': np.nan, 'None': np.nan, '': np.nan})

                is_id_column = (col == id_col)
                if not is_id_column and casing_rule != 'none':
                    if casing_rule == 'title':
                        df[col] = df[col].str.title()
                    elif casing_rule == 'upper':
                        df[col] = df[col].str.upper()
                    elif casing_rule == 'lower':
                        df[col] = df[col].str.lower()
                text_columns_cleaned.append(col)

        # 5. Convert numeric columns safely (based on expected schema)
        numeric_conversions = []
        for col, rules in EXPECTED_SCHEMA.items():
            if col in df.columns and rules['type'] == 'numeric':
                df[col] = pd.to_numeric(df[col], errors='coerce')
                numeric_conversions.append(col)

        # 6. Standardize date formats to ISO YYYY-MM-DD
        date_columns_standardized = []
        for col, rules in EXPECTED_SCHEMA.items():
            if col in df.columns and rules['type'] == 'datetime':
                df[col] = pd.to_datetime(df[col], errors='coerce')
                date_columns_standardized.append(col)

        # 7. Handle missing values: numeric -> median, categorical -> mode/configurable default
        nulls_filled = 0
        missing_value_actions = {}
        for col in df.columns:
            null_count = int(df[col].isnull().sum())
            if null_count == 0:
                continue

            rule_type = EXPECTED_SCHEMA.get(col, {}).get('type')

            if col in date_columns_standardized:
                # Fill missing dates with the most frequent (mode) date, else today
                if df[col].notnull().any():
                    fill_val = df[col].mode().iloc[0]
                else:
                    fill_val = pd.Timestamp.now().normalize()
                df[col] = df[col].fillna(fill_val)
                missing_value_actions[col] = f"filled {null_count} missing date(s) with mode"
            elif rule_type == 'numeric' or pd.api.types.is_numeric_dtype(df[col]):
                median_val = df[col].median()
                if pd.isna(median_val):
                    median_val = 0.0
                df[col] = df[col].fillna(median_val)
                missing_value_actions[col] = f"filled {null_count} missing value(s) with median ({median_val})"
            else:
                # Categorical -> mode, fallback to 'Unknown' / 'UNKNOWN_ID' for the key column
                if col == id_col:
                    df[col] = df[col].fillna('UNKNOWN_ID')
                    missing_value_actions[col] = f"filled {null_count} missing ID(s) with placeholder"
                else:
                    mode_series = df[col].mode()
                    fill_val = mode_series.iloc[0] if not mode_series.empty else 'Unknown'
                    df[col] = df[col].fillna(fill_val)
                    missing_value_actions[col] = f"filled {null_count} missing value(s) with mode ('{fill_val}')"

            nulls_filled += null_count

        # Finalize date formatting to ISO strings for CSV output
        for col in date_columns_standardized:
            df[col] = df[col].dt.strftime('%Y-%m-%d')

        # Save cleaned dataset to uploads/cleaned/<uuid>/
        cleaned_dir = os.path.join(current_app.config['UPLOAD_CLEANED_DIR'], dataset_uuid)
        os.makedirs(cleaned_dir, exist_ok=True)

        cleaned_path = os.path.join(cleaned_dir, dataset.original_filename)
        df.to_csv(cleaned_path, index=False)

        # Update database metadata
        dataset.cleaned_filepath = cleaned_path
        dataset.row_count = len(df)
        db.session.commit()

        summary = {
            'original_rows': original_rows,
            'cleaned_rows': len(df),
            'original_columns': original_columns,
            'empty_rows_removed': int(empty_rows_removed),
            'duplicates_removed': int(duplicates_removed),
            'nulls_filled': int(nulls_filled),
            'missing_value_actions': missing_value_actions,
            'numeric_conversions': numeric_conversions,
            'date_columns_standardized': date_columns_standardized,
            'text_columns_cleaned': text_columns_cleaned,
            'casing_rule': casing_rule,
            'cleaned_filepath': cleaned_path
        }

        summary_path = os.path.join(cleaned_dir, 'cleaning_summary.json')
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=4, default=str)

        update_pipeline_stage(dataset_uuid, 'Cleaning', 'Completed')

        log_msg = (
            f"Data cleaning completed. Rows: {original_rows} -> {len(df)}. "
            f"Empty rows removed: {empty_rows_removed}. Duplicates removed: {duplicates_removed}. "
            f"Nulls filled: {nulls_filled}."
        )
        pipeline_logger.info(log_msg)
        log_activity(log_msg, level='INFO', dataset_id=dataset.id, stage='Cleaning')

        return summary
    except Exception as e:
        error_msg = f"Fatal data cleaning failure: {str(e)}"
        error_logger.error(error_msg)
        update_pipeline_stage(dataset_uuid, 'Cleaning', 'Failed', error_message=error_msg)
        raise e
