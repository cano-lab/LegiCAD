#!/usr/bin/env python3
"""
logging_config.py - Centralized logging configuration for ArchEngine generators

Provides consistent logging across all generator scripts with:
- Console and file logging
- Color-coded console output
- Detailed file logs
- Progress tracking
- Performance timing
"""

import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable
from contextlib import contextmanager
import time
import functools


# =============================================================================
# CUSTOM LOG LEVELS
# =============================================================================

# Add a SUCCESS level between INFO and WARNING
SUCCESS = 25
logging.addLevelName(SUCCESS, 'SUCCESS')


def success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS):
        self._log(SUCCESS, message, args, **kwargs)


logging.Logger.success = success


# =============================================================================
# COLOR FORMATTER FOR CONSOLE
# =============================================================================

class ColoredFormatter(logging.Formatter):
    """Logging formatter with ANSI color codes for console output."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[37m',       # White
        'SUCCESS': '\033[32m',    # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'

    def __init__(self, fmt=None, datefmt=None, use_colors=True):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and sys.stdout.isatty()

    def format(self, record):
        if self.use_colors:
            color = self.COLORS.get(record.levelname, self.RESET)
            record.levelname = f"{color}{self.BOLD}{record.levelname}{self.RESET}"
            record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


class DetailedFormatter(logging.Formatter):
    """Detailed formatter for file logging."""

    def format(self, record):
        # Add extra context
        record.module_path = f"{record.module}.{record.funcName}"
        return super().format(record)


# =============================================================================
# PROGRESS HANDLER
# =============================================================================

class ProgressHandler(logging.Handler):
    """Handler that tracks progress for long-running operations."""

    def __init__(self, total_steps: int = 100):
        super().__init__()
        self.total_steps = total_steps
        self.current_step = 0
        self.current_task = ""
        self.start_time = None

    def emit(self, record):
        # Check for progress updates in the record
        if hasattr(record, 'progress_step'):
            self.current_step = record.progress_step
        if hasattr(record, 'progress_task'):
            self.current_task = record.progress_task

    def start(self):
        self.start_time = time.time()
        self.current_step = 0

    def update(self, step: int, task: str = ""):
        self.current_step = step
        self.current_task = task

    def get_progress(self) -> dict:
        elapsed = time.time() - self.start_time if self.start_time else 0
        percent = (self.current_step / self.total_steps * 100) if self.total_steps > 0 else 0
        return {
            'step': self.current_step,
            'total': self.total_steps,
            'percent': percent,
            'elapsed': elapsed,
            'task': self.current_task
        }


# =============================================================================
# LOGGER SETUP
# =============================================================================

def setup_logging(
    name: str = 'archengine',
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None,
    console: bool = True,
    colors: bool = True,
    detailed: bool = False
) -> logging.Logger:
    """
    Set up logging for ArchEngine generators.

    Args:
        name: Logger name
        level: Logging level
        log_file: Specific log file path
        log_dir: Directory for auto-generated log files
        console: Enable console output
        colors: Enable colored console output
        detailed: Enable detailed formatting

    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        if detailed:
            console_format = '%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s'
        else:
            console_format = '%(levelname)-8s | %(message)s'

        console_formatter = ColoredFormatter(console_format, use_colors=colors)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # File handler
    if log_file or log_dir:
        if log_file:
            file_path = Path(log_file)
        else:
            log_dir_path = Path(log_dir)
            log_dir_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_path = log_dir_path / f"{name}_{timestamp}.log"

        file_handler = logging.FileHandler(file_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # Capture everything in file

        file_format = '%(asctime)s | %(levelname)-8s | %(name)s:%(module)s:%(lineno)d | %(message)s'
        file_formatter = DetailedFormatter(file_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        logger.debug(f"Logging to file: {file_path}")

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Get a logger for a module.

    Args:
        name: Module name (defaults to caller's module)

    Returns:
        Logger instance
    """
    if name is None:
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back:
            name = frame.f_back.f_globals.get('__name__', 'archengine')

    return logging.getLogger(f'archengine.{name}')


# =============================================================================
# DECORATORS
# =============================================================================

def log_function_call(logger: logging.Logger = None, level: int = logging.DEBUG):
    """Decorator to log function entry and exit."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)

            func_name = func.__name__
            logger.log(level, f"Entering {func_name}")

            try:
                result = func(*args, **kwargs)
                logger.log(level, f"Exiting {func_name}")
                return result
            except Exception as e:
                logger.error(f"Exception in {func_name}: {e}")
                raise

        return wrapper
    return decorator


def log_execution_time(logger: logging.Logger = None, level: int = logging.INFO):
    """Decorator to log function execution time."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)

            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time

            func_name = func.__name__
            logger.log(level, f"{func_name} completed in {elapsed:.2f}s")

            return result
        return wrapper
    return decorator


# =============================================================================
# CONTEXT MANAGERS
# =============================================================================

@contextmanager
def log_section(logger: logging.Logger, title: str, level: int = logging.INFO):
    """Context manager to log the start and end of a section."""
    separator = "=" * 60
    logger.log(level, separator)
    logger.log(level, title.upper())
    logger.log(level, separator)

    start_time = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        logger.log(level, f"{title} completed in {elapsed:.2f}s")
        logger.log(level, "")


@contextmanager
def log_step(logger: logging.Logger, step: str, level: int = logging.INFO):
    """Context manager to log a processing step."""
    logger.log(level, f"Starting: {step}...")
    start_time = time.time()

    try:
        yield
        elapsed = time.time() - start_time
        logger.success(f"Completed: {step} ({elapsed:.2f}s)")
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Failed: {step} ({elapsed:.2f}s) - {e}")
        raise


# =============================================================================
# PROGRESS LOGGING
# =============================================================================

class ProgressLogger:
    """Helper class for logging progress of multi-step operations."""

    def __init__(self, logger: logging.Logger, total_steps: int, operation: str = "Processing"):
        self.logger = logger
        self.total_steps = total_steps
        self.current_step = 0
        self.operation = operation
        self.start_time = time.time()

    def step(self, message: str = ""):
        """Log completion of a step."""
        self.current_step += 1
        percent = (self.current_step / self.total_steps * 100) if self.total_steps > 0 else 0
        elapsed = time.time() - self.start_time

        step_msg = f"[{self.current_step}/{self.total_steps}] ({percent:.0f}%)"
        if message:
            step_msg += f" {message}"

        self.logger.info(step_msg)

    def complete(self):
        """Log completion of all steps."""
        elapsed = time.time() - self.start_time
        self.logger.success(f"{self.operation} complete: {self.total_steps} steps in {elapsed:.2f}s")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def log_dict(logger: logging.Logger, data: dict, title: str = "Data", level: int = logging.DEBUG):
    """Log a dictionary in a formatted way."""
    import json
    logger.log(level, f"{title}:")
    for line in json.dumps(data, indent=2).split('\n'):
        logger.log(level, f"  {line}")


def log_exception(logger: logging.Logger, exc: Exception, context: str = ""):
    """Log an exception with full traceback."""
    import traceback
    if context:
        logger.error(f"Exception in {context}: {exc}")
    else:
        logger.error(f"Exception: {exc}")
    logger.debug("".join(traceback.format_tb(exc.__traceback__)))


def silence_library_loggers():
    """Silence noisy third-party loggers."""
    noisy_loggers = ['PIL', 'matplotlib', 'urllib3', 'requests']
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)


# =============================================================================
# MAIN - DEMONSTRATION
# =============================================================================

if __name__ == '__main__':
    # Demo logging setup
    logger = setup_logging(
        name='archengine.demo',
        level=logging.DEBUG,
        console=True,
        colors=True,
        detailed=True
    )

    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.success("This is a success message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")

    print()

    # Demo section logging
    with log_section(logger, "Demo Section"):
        with log_step(logger, "Step 1"):
            time.sleep(0.1)
        with log_step(logger, "Step 2"):
            time.sleep(0.2)

    # Demo progress logging
    print()
    progress = ProgressLogger(logger, 5, "Demo Progress")
    for i in range(5):
        time.sleep(0.1)
        progress.step(f"Processing item {i+1}")
    progress.complete()
