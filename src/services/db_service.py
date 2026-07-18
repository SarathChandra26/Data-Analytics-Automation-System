import uuid
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from src.utils.logger import app_logger, pipeline_logger, error_logger

db = SQLAlchemy()

class Dataset(db.Model):
    __tablename__ = 'datasets'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    dataset_name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    raw_filepath = db.Column(db.String(500), nullable=True)
    cleaned_filepath = db.Column(db.String(500), nullable=True)
    transformed_filepath = db.Column(db.String(500), nullable=True)
    archive_filepath = db.Column(db.String(500), nullable=True)
    file_size_bytes = db.Column(db.Integer, default=0)
    row_count = db.Column(db.Integer, default=0)
    column_count = db.Column(db.Integer, default=0)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Pending')  # 'Pending', 'Running', 'Completed', 'Failed'
    
    stages = relationship("PipelineStage", backref="dataset", cascade="all, delete-orphan")

class PipelineStage(db.Model):
    __tablename__ = 'pipeline_stages'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False)
    stage_name = db.Column(db.String(50), nullable=False)  # 'Upload', 'Validation', 'Cleaning', etc.
    status = db.Column(db.String(20), default='Pending')   # 'Pending', 'Running', 'Completed', 'Failed'
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

class AnalyticsRecord(db.Model):
    """Standardized analytics table that holds transformed transaction records for all datasets."""
    __tablename__ = 'analytics_data'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False)
    transaction_id = db.Column(db.String(100), nullable=True)
    transaction_date = db.Column(db.String(20), nullable=True)
    product_category = db.Column(db.String(150), nullable=True)
    units_sold = db.Column(db.Float, nullable=True)
    unit_price = db.Column(db.Float, nullable=True)
    revenue = db.Column(db.Float, nullable=True)
    revenue_percentage_of_total = db.Column(db.Float, nullable=True)
    customer_segment = db.Column(db.String(150), nullable=True)
    region = db.Column(db.String(150), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    month = db.Column(db.Integer, nullable=True)
    month_name = db.Column(db.String(20), nullable=True)
    quarter = db.Column(db.String(5), nullable=True)
    day_of_week = db.Column(db.String(15), nullable=True)


class AnalyticsTableMeta(db.Model):
    """Tracks import metadata for each dataset loaded into the standardized analytics table."""
    __tablename__ = 'analytics_table_meta'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False, unique=True)
    table_name = db.Column(db.String(100), default='analytics_data')
    record_count = db.Column(db.Integer, default=0)
    column_count = db.Column(db.Integer, default=0)
    source_filepath = db.Column(db.String(500), nullable=True)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_status = db.Column(db.String(20), default='Pending')  # 'Completed', 'Failed'


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    level = db.Column(db.String(10), default='INFO')  # 'INFO', 'WARNING', 'ERROR'
    message = db.Column(db.Text, nullable=False)
    dataset_id = db.Column(db.Integer, nullable=True)
    stage = db.Column(db.String(50), nullable=True)

# Helper Functions
def init_db(app):
    """Initializes SQLite database within Flask application context."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        app_logger.info("SQLite database tables initialized successfully.")

def create_dataset_record(dataset_uuid: str, name: str, original_filename: str, raw_filepath: str, file_size: int) -> Dataset:
    """Creates a new dataset metadata row and sets initial pipeline stages status."""
    try:
        new_dataset = Dataset(
            uuid=dataset_uuid,
            dataset_name=name,
            original_filename=original_filename,
            raw_filepath=raw_filepath,
            file_size_bytes=file_size,
            status='Pending'
        )
        db.session.add(new_dataset)
        db.session.flush()  # to obtain the autogenerated ID
        
        stages = [
            'Upload', 'Validation', 'Cleaning', 'Transformation', 
            'Database', 'Analytics', 'Visualization', 'Excel_Report', 'PDF_Report', 'Archive'
        ]
        
        for stage in stages:
            stage_status = 'Completed' if stage == 'Upload' else 'Pending'
            started = datetime.utcnow() if stage == 'Upload' else None
            completed = datetime.utcnow() if stage == 'Upload' else None
            
            new_stage = PipelineStage(
                dataset_id=new_dataset.id,
                stage_name=stage,
                status=stage_status,
                started_at=started,
                completed_at=completed
            )
            db.session.add(new_stage)
            
        db.session.commit()
        
        # Log to physical log and DB
        log_msg = f"Dataset registered: {name} ({original_filename}), UUID: {dataset_uuid}"
        pipeline_logger.info(log_msg)
        log_activity(log_msg, level='INFO', dataset_id=new_dataset.id, stage='Upload')
        
        return new_dataset
    except Exception as e:
        db.session.rollback()
        error_logger.error(f"Error registering dataset metadata: {str(e)}")
        raise e

def update_pipeline_stage(dataset_uuid: str, stage_name: str, status: str, error_message: str = None):
    """Updates the execution status and timing for a dataset's pipeline stage."""
    try:
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")
            
        stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name=stage_name).first()
        if not stage:
            raise ValueError(f"Pipeline stage {stage_name} not found for dataset {dataset_uuid}.")
            
        stage.status = status
        if status == 'Running':
            stage.started_at = datetime.utcnow()
            stage.completed_at = None
            stage.error_message = None
        elif status in ('Completed', 'Failed'):
            stage.completed_at = datetime.utcnow()
            if error_message:
                stage.error_message = error_message
                
        # Update overall dataset status based on stages
        if status == 'Failed':
            dataset.status = 'Failed'
        elif stage_name == 'Archive' and status == 'Completed':
            dataset.status = 'Completed'
        elif status == 'Running':
            dataset.status = 'Running'
            
        db.session.commit()
        
        # Log to file and database activity log
        log_msg = f"Stage {stage_name} updated to {status}"
        if error_message:
            log_msg += f". Error: {error_message}"
            
        if status == 'Failed':
            pipeline_logger.error(log_msg)
            log_activity(log_msg, level='ERROR', dataset_id=dataset.id, stage=stage_name)
        else:
            pipeline_logger.info(log_msg)
            log_activity(log_msg, level='INFO', dataset_id=dataset.id, stage=stage_name)
            
    except Exception as e:
        db.session.rollback()
        error_logger.error(f"Failed to update pipeline stage: {str(e)}")
        raise e

def log_activity(message: str, level: str = 'INFO', dataset_id: int = None, stage: str = None):
    """Inserts a system activity log entry into the database."""
    try:
        log_entry = ActivityLog(
            level=level,
            message=message,
            dataset_id=dataset_id,
            stage=stage
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Fallback to standard logging to prevent infinite loops/app crashes
        error_logger.error(f"Failed to write database activity log: {str(e)}")
