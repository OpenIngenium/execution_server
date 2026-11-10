"""Unit tests for ``ingenium_embedded.logging_util``."""

import logging

from ingenium_embedded import logging_util


class TestLoggingUtil:
    def test_logger_is_configured(self):
        assert logging_util.logger is not None

    def test_set_level_updates_logger(self, capsys):
        original = logging_util.logger.level
        try:
            logging_util.set_level("WARNING")
            assert logging_util.logger.level == logging.WARNING
            captured = capsys.readouterr()
            assert "Logger level set to: WARNING" in captured.out
        finally:
            logging_util.logger.setLevel(original)
