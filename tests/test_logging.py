import io
import json
import logging

from utils.logging import JSONFormatter, get_logger, setup_logging


def test_json_formatter_outputs_valid_json():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Test log message",
        args=(),
        exc_info=None,
        func="test_func",
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test_logger"
    assert parsed["message"] == "Test log message"
    assert parsed["function"] == "test_func"
    assert parsed["line"] == 42
    assert "timestamp" in parsed


def test_json_formatter_includes_extra_fields():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.WARNING,
        pathname="test.py",
        lineno=10,
        msg="Warning message",
        args=(),
        exc_info=None,
        func="test_extra",
    )
    record.job_id = "job-12345"
    record.event = "job_failed"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["extra"]["job_id"] == "job-12345"
    assert parsed["extra"]["event"] == "job_failed"


def test_setup_logging_configures_stream():
    buf = io.StringIO()
    setup_logging(log_level="INFO", json_format=True, stream=buf)
    logger = get_logger("test.setup")

    logger.info("Structured log test", extra={"event": "test_event"})

    output = buf.getvalue().strip()
    assert output != ""
    parsed = json.loads(output)
    assert parsed["message"] == "Structured log test"
    assert parsed["extra"]["event"] == "test_event"
