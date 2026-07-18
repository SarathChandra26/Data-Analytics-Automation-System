import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Sets up a logger with a rotating file handler and console handler."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s:%(filename)s:%(lineno)d] - %(message)s'
    )

    # File Handler (rotating at 5MB, keeping 5 backups)
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Define paths relative to this file
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Initialize standard loggers
app_logger = setup_logger('application', os.path.join(LOGS_DIR, 'application.log'))
pipeline_logger = setup_logger('pipeline', os.path.join(LOGS_DIR, 'pipeline.log'))
error_logger = setup_logger('error', os.path.join(LOGS_DIR, 'error.log'), level=logging.ERROR)
