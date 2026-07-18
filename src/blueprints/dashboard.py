import os
from flask import Blueprint, render_template, current_app
from src.services.db_service import Dataset, PipelineStage, ActivityLog, db

dashboard_bp = Blueprint('dashboard', __name__)

def get_storage_used() -> str:
    """Calculates total size of all uploaded files in MB."""
    total_bytes = 0
    dirs = [
        current_app.config['UPLOAD_RAW_DIR'],
        current_app.config['UPLOAD_CLEANED_DIR'],
        current_app.config['UPLOAD_ARCHIVE_DIR']
    ]
    for d in dirs:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for f in files:
                    total_bytes += os.path.getsize(os.path.join(root, f))
    return f"{total_bytes / (1024 * 1024):.2f} MB"

@dashboard_bp.route('/')
def index():
    """Serves the main dashboard page and calculates all enterprise-level KPIs."""
    datasets = Dataset.query.order_by(Dataset.upload_time.desc()).all()
    
    # Calculate KPIs
    total_datasets = len(datasets)
    pipeline_runs = total_datasets
    
    # Reports generated: count how many datasets completed reports (either PDF or Excel)
    completed_reports = 0
    total_rows_processed = 0
    success_count = 0
    failed_count = 0
    
    for d in datasets:
        # Check if pipeline completed successfully
        if d.status == 'Completed':
            success_count += 1
            total_rows_processed += (d.row_count or 0)
        elif d.status == 'Failed':
            failed_count += 1
            
        # Count report stage completion
        pdf_stage = PipelineStage.query.filter_by(dataset_id=d.id, stage_name='PDF_Report').first()
        excel_stage = PipelineStage.query.filter_by(dataset_id=d.id, stage_name='Excel_Report').first()
        if (pdf_stage and pdf_stage.status == 'Completed') or (excel_stage and excel_stage.status == 'Completed'):
            completed_reports += 1
            
    success_rate = 100.0
    if pipeline_runs > 0:
        success_rate = (success_count / (success_count + failed_count)) * 100 if (success_count + failed_count) > 0 else 100.0
        
    storage_used = get_storage_used()
    
    # Recent activity logs
    recent_logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(8).all()
    
    return render_template(
        'dashboard.html',
        datasets=datasets,
        kpis={
            'total_datasets': total_datasets,
            'reports_generated': completed_reports,
            'rows_processed': f"{total_rows_processed:,}",
            'success_rate': f"{success_rate:.1f}%",
            'pipeline_runs': pipeline_runs,
            'storage_used': storage_used
        },
        recent_logs=recent_logs
    )
