import os

class Config:
    """Base configuration settings for DA Automation System (DAAS)."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_key_dataflow_ai_2026')
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    
    # Database
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'dataflow_ai.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload Directories
    UPLOAD_RAW_DIR = os.path.join(BASE_DIR, 'uploads', 'raw')
    UPLOAD_CLEANED_DIR = os.path.join(BASE_DIR, 'uploads', 'cleaned')
    UPLOAD_TRANSFORMED_DIR = os.path.join(BASE_DIR, 'uploads', 'transformed')
    UPLOAD_ARCHIVE_DIR = os.path.join(BASE_DIR, 'uploads', 'archive')
    
    # Reports & Visualizations Directories
    REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
    CHARTS_DIR = os.path.join(BASE_DIR, 'charts')
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    
    # File upload configurations
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
    ALLOWED_EXTENSIONS = {'csv'}
