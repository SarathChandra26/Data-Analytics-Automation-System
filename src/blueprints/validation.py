import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash
from src.services.db_service import Dataset, PipelineStage
from src.services.validation_service import validate_dataset_schema
from src.utils.logger import app_logger

validation_bp = Blueprint('validation', __name__)

@validation_bp.route('/validation/<uuid>')
def details(uuid):
    """Computes schema validation results if pending, then displays validation summary."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))
        
    validation_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Validation').first()
    
    summary_path = os.path.join(os.path.dirname(dataset.raw_filepath), 'validation_summary.json')
    
    # If pending or running, or if summary doesn't exist, trigger validation synchronously
    if (validation_stage and validation_stage.status == 'Pending') or not os.path.exists(summary_path):
        try:
            validate_dataset_schema(uuid)
        except Exception as e:
            flash(f"Validation failed: {str(e)}", "error")
            return redirect(url_for('dashboard.index'))
            
    # Load validation summary file
    try:
        with open(summary_path, 'r') as f:
            summary = json.load(f)
    except Exception as e:
        app_logger.error(f"Failed to read validation summary: {str(e)}")
        summary = {
            'status': 'Failed',
            'errors': [f"Could not load validation summary: {str(e)}"],
            'warnings': [],
            'missing_required_columns': [],
            'duplicate_id_details': [],
            'null_counts': {},
            'invalid_types': {}
        }
        
    return render_template(
        'validation.html',
        dataset=dataset,
        summary=summary,
        validation_stage=validation_stage
    )
