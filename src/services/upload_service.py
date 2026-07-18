import os
import uuid
import pandas as pd
import numpy as np
from werkzeug.utils import secure_filename
from flask import current_app
from src.services.db_service import create_dataset_record, Dataset, db
from src.utils.logger import app_logger, error_logger

def allowed_file(filename: str) -> bool:
    """Checks if the uploaded file has a valid CSV extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv'}

def format_file_size(size_in_bytes: int) -> str:
    """Formats raw byte sizes into human-readable strings (KB, MB)."""
    if size_in_bytes < 1024:
        return f"{size_in_bytes} Bytes"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.2f} KB"
    else:
        return f"{size_in_bytes / (1024 * 1024):.2f} MB"

def generate_dataset_summary(file_path: str) -> dict:
    """Reads CSV file and computes metadata & data quality metrics using Pandas."""
    try:
        # Read dataset (using a limit of 100K rows for safety if it's huge, but for CSE project we do full scan)
        df = pd.read_csv(file_path)
        
        row_count = len(df)
        col_count = len(df.columns)
        
        # Numeric vs Categorical
        numeric_cols = []
        categorical_cols = []
        
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                numeric_cols.append(col)
            else:
                categorical_cols.append(col)
                
        # Missing values analysis
        missing_by_col = df.isnull().sum()
        total_missing = int(missing_by_col.sum())
        missing_details = {col: int(val) for col, val in missing_by_col.items() if val > 0}
        
        # Duplicate rows count
        duplicate_rows = int(df.duplicated().sum())
        
        summary = {
            'row_count': row_count,
            'column_count': col_count,
            'numeric_columns_count': len(numeric_cols),
            'numeric_columns': numeric_cols,
            'categorical_columns_count': len(categorical_cols),
            'categorical_columns': categorical_cols,
            'missing_values_count': total_missing,
            'missing_values_by_column': missing_details,
            'duplicate_rows_count': duplicate_rows
        }
        
        return summary
    except Exception as e:
        error_logger.error(f"Failed to generate dataset summary for {file_path}: {str(e)}")
        raise e

def save_uploaded_file(file, dataset_name: str) -> dict:
    """Validates, stores raw upload, generates metrics, and records metadata in database."""
    if not file or file.filename == '':
        raise ValueError("No file selected for upload.")
        
    if not allowed_file(file.filename):
        raise ValueError("Unsupported file format. Please upload a CSV file.")
        
    original_filename = secure_filename(file.filename)
    
    # Generate unique UUID for this dataset run
    dataset_uuid = str(uuid.uuid4())
    
    # Define folder: uploads/raw/<uuid>/
    raw_dir = os.path.join(current_app.config['UPLOAD_RAW_DIR'], dataset_uuid)
    os.makedirs(raw_dir, exist_ok=True)
    
    file_path = os.path.join(raw_dir, original_filename)
    file.save(file_path)
    
    # Calculate file size
    file_size = os.path.getsize(file_path)
    
    try:
        # Generate summary metrics
        summary = generate_dataset_summary(file_path)
        
        # Insert dataset row in DB
        new_dataset = create_dataset_record(
            dataset_uuid=dataset_uuid,
            name=dataset_name or original_filename.rsplit('.', 1)[0],
            original_filename=original_filename,
            raw_filepath=file_path,
            file_size=file_size
        )
        
        # Update row and col count in datasets table
        new_dataset.row_count = summary['row_count']
        new_dataset.column_count = summary['column_count']
        db.session.commit()
        
        # Combine database info and pandas metrics
        result = {
            'uuid': dataset_uuid,
            'dataset_name': new_dataset.dataset_name,
            'original_filename': original_filename,
            'file_size_formatted': format_file_size(file_size),
            'upload_time': new_dataset.upload_time.strftime('%Y-%m-%d %H:%M:%S'),
            'summary': summary
        }
        
        return result
    except Exception as e:
        # Clean up files if processing failed
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(raw_dir):
            os.rmdir(raw_dir)
        error_logger.error(f"Failed to process and register upload: {str(e)}")
        raise e
