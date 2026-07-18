import os
import pandas as pd
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from src.services.upload_service import save_uploaded_file, allowed_file
from src.utils.logger import app_logger, error_logger

upload_bp = Blueprint('upload', __name__)

@upload_bp.route('/upload', methods=['GET'])
def index():
    """Serves the dataset upload interface page."""
    return render_template('upload.html')

@upload_bp.route('/upload/ajax', methods=['POST'])
def upload_ajax():
    """Handles async AJAX CSV upload, calculates data metrics, and extracts preview rows."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part in request.'}), 400
        
    file = request.files['file']
    dataset_name = request.form.get('dataset_name', '').strip()
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected.'}), 400
        
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Only CSV files are supported.'}), 400
        
    try:
        # Save file, generate statistics and metadata
        result = save_uploaded_file(file, dataset_name)
        
        # Load the CSV again to extract the preview (only head of 10 rows)
        file_path = os.path.join(
            current_app_config_upload_dir_helper(result['uuid']),
            result['original_filename']
        )
        
        df = pd.read_csv(file_path, nrows=10)
        
        # Format df for dynamic HTML table preview
        preview_headers = list(df.columns)
        preview_rows = df.fillna("").to_dict(orient='records')
        
        result['preview_headers'] = preview_headers
        result['preview_rows'] = preview_rows
        result['success'] = True
        
        app_logger.info(f"AJAX Upload successful for dataset UUID {result['uuid']}")
        return jsonify(result)
        
    except Exception as e:
        error_msg = str(e)
        error_logger.error(f"Error handling AJAX upload: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500

def current_app_config_upload_dir_helper(dataset_uuid: str) -> str:
    """Helper to fetch raw uploads directory route from Flask app config."""
    from flask import current_app
    return os.path.join(current_app.config['UPLOAD_RAW_DIR'], dataset_uuid)
