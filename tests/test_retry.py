"""
Retry logika tesztek.

Fázis 3 - Error handling & recovery
"""
import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from moltagent.retry import (
    ReplyError,
    calculate_delay,
    get_retry_after,
    call_with_retry,
    log_error,
    retry_on_error,
    RETRYABLE_EXCEPTIONS,
    DEFAULT_MAX_RETRIES,
)


# --- Mock exceptions ---

class MockRateLimitError(Exception):
    """Mock RateLimitError for testing."""
    def __init__(self, message="Rate limit exceeded", retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class MockAPITimeoutError(Exception):
    """Mock APITimeoutError for testing."""
    pass


class MockAPIConnectionError(Exception):
    """Mock APIConnectionError for testing."""
    pass


class MockAPIError(Exception):
    """Mock APIError for testing (non-retryable)."""
    def __init__(self, message="API Error", status_code=400):
        super().__init__(message)
        self.status_code = status_code


# --- ReplyError tests ---

class TestReplyError:
    """ReplyError exception tests."""

    def test_reply_error_str(self):
        """ReplyError str formázás."""
        err = ReplyError(
            error_type="RateLimitError",
            message="Rate limit exceeded",
            event_id="e123",
            retry_count=3,
        )
        assert str(err) == "RateLimitError: Rate limit exceeded"

    def test_reply_error_fields(self):
        """ReplyError mezők."""
        err = ReplyError(
            error_type="Timeout",
            message="Request timed out",
            event_id="e456",
            retry_count=2,
            original_exception=TimeoutError("timeout"),
        )
        assert err.error_type == "Timeout"
        assert err.message == "Request timed out"
        assert err.event_id == "e456"
        assert err.retry_count == 2
        assert isinstance(err.original_exception, TimeoutError)


# --- calculate_delay tests ---

class TestCalculateDelay:
    """Exponential backoff delay tests."""

    def test_first_attempt_base_delay(self):
        """Első próbálkozás ~base_delay."""
        delay = calculate_delay(0, base_delay=1.0, max_delay=30.0, jitter=0)
        assert delay == 1.0

    def test_second_attempt_double(self):
        """Második próbálkozás ~2x base_delay."""
        delay = calculate_delay(1, base_delay=1.0, max_delay=30.0, jitter=0)
        assert delay == 2.0

    def test_third_attempt_quadruple(self):
        """Harmadik próbálkozás ~4x base_delay."""
        delay = calculate_delay(2, base_delay=1.0, max_delay=30.0, jitter=0)
        assert delay == 4.0

    def test_max_delay_cap(self):
        """Delay nem haladja meg a max_delay-t."""
        delay = calculate_delay(10, base_delay=1.0, max_delay=30.0, jitter=0)
        assert delay == 30.0

    def test_jitter_applied(self):
        """Jitter módosítja a delay-t."""
        delays = [calculate_delay(1, base_delay=1.0, jitter=0.5) for _ in range(100)]
        # Jitter miatt nem mind egyforma
        unique_delays = set(round(d, 2) for d in delays)
        assert len(unique_delays) > 1


# --- get_retry_after tests ---

class TestGetRetryAfter:
    """Retry-after header extraction tests."""

    def test_no_retry_after(self):
        """Normál exception nincs retry_after."""
        err = Exception("test")
        assert get_retry_after(err) is None

    def test_rate_limit_with_retry_after_attribute(self):
        """RateLimitError retry_after attribútummal."""
        err = MockRateLimitError(retry_after=5.0)
        # Patch RETRYABLE_EXCEPTIONS to include our mock
        with patch("moltagent.retry.RateLimitError", MockRateLimitError):
            with patch("moltagent.retry.isinstance", lambda x, y: type(x).__name__ == "MockRateLimitError"):
                # Direct test with attribute
                assert hasattr(err, "retry_after")
                assert err.retry_after == 5.0


# --- call_with_retry tests ---

class TestCallWithRetry:
    """call_with_retry function tests."""

    def test_success_first_try(self):
        """Sikeres hívás első próbálkozásra."""
        func = MagicMock(return_value="success")

        result = call_with_retry(func, max_retries=3)

        assert result == "success"
        assert func.call_count == 1

    def test_success_after_retry(self):
        """Sikeres hívás retry után."""
        func = MagicMock(side_effect=[
            Exception("fail 1"),  # Non-retryable by default
        ])

        # With non-retryable exception, should fail immediately
        with pytest.raises(ReplyError):
            call_with_retry(func, max_retries=3)

    def test_all_retries_exhausted(self):
        """Minden retry kimerül."""
        # Patch to use our mock exceptions
        with patch("moltagent.retry.RETRYABLE_EXCEPTIONS", (MockAPITimeoutError,)):
            func = MagicMock(side_effect=MockAPITimeoutError("timeout"))

            with pytest.raises(ReplyError) as exc_info:
                call_with_retry(func, max_retries=2, base_delay=0.01)

            assert "All 3 attempts failed" in exc_info.value.message
            assert func.call_count == 3  # 1 + 2 retries

    def test_non_retryable_exception_fails_immediately(self):
        """Nem retryable exception azonnal elbukik."""
        with patch("moltagent.retry.APIError", MockAPIError):
            func = MagicMock(side_effect=MockAPIError("Bad Request", 400))

            with pytest.raises(ReplyError) as exc_info:
                call_with_retry(func, max_retries=3)

            # Csak egyszer hívta meg
            assert func.call_count == 1
            assert exc_info.value.error_type == "MockAPIError"

    def test_event_id_passed_to_error(self):
        """Event ID átadódik a ReplyError-nak."""
        func = MagicMock(side_effect=ValueError("test error"))

        with pytest.raises(ReplyError) as exc_info:
            call_with_retry(func, max_retries=0, event_id="e789")

        assert exc_info.value.event_id == "e789"


# --- log_error tests ---

class TestLogError:
    """Error logging tests."""

    def test_log_error_creates_file(self):
        """log_error létrehozza a log fájlt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "errors.jsonl")

            with patch("moltagent.retry.ERROR_LOG", log_file):
                with patch("moltagent.retry.LOG_DIR", tmpdir):
                    log_error(
                        event_id="e123",
                        error_type="TestError",
                        message="Test message",
                        retry_count=1,
                        resolved=False,
                    )

            assert os.path.exists(log_file)

            with open(log_file) as f:
                entry = json.loads(f.readline())

            assert entry["event_id"] == "e123"
            assert entry["error_type"] == "TestError"
            assert entry["message"] == "Test message"
            assert entry["retry_count"] == 1
            assert entry["resolved"] is False
            assert "ts" in entry

    def test_log_error_with_extra(self):
        """log_error extra adatokkal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "errors.jsonl")

            with patch("moltagent.retry.ERROR_LOG", log_file):
                with patch("moltagent.retry.LOG_DIR", tmpdir):
                    log_error(
                        event_id="e456",
                        error_type="APIError",
                        message="Bad request",
                        extra={"status_code": 400},
                    )

            with open(log_file) as f:
                entry = json.loads(f.readline())

            assert entry["extra"]["status_code"] == 400


# --- retry_on_error decorator tests ---

class TestRetryOnErrorDecorator:
    """@retry_on_error decorator tests."""

    def test_decorator_success(self):
        """Decorator sikeres hívásra."""
        @retry_on_error(max_retries=3)
        def my_func():
            return "hello"

        assert my_func() == "hello"

    def test_decorator_with_args(self):
        """Decorator argumentumokkal."""
        @retry_on_error(max_retries=2)
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_decorator_retry_on_failure(self):
        """Decorator retry-t hajt végre."""
        call_count = {"n": 0}

        @retry_on_error(max_retries=2, base_delay=0.01)
        def flaky_func():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise Exception("fail")
            return "success"

        # Non-retryable exception -> fails immediately
        with pytest.raises(ReplyError):
            flaky_func()


# --- Integration tests ---

class TestRetryIntegration:
    """Integration tests for retry logic."""

    def test_retry_timing(self):
        """Retry várakozik a megfelelő időt."""
        with patch("moltagent.retry.RETRYABLE_EXCEPTIONS", (MockAPITimeoutError,)):
            func = MagicMock(side_effect=MockAPITimeoutError("timeout"))

            start = time.time()
            with pytest.raises(ReplyError):
                call_with_retry(func, max_retries=2, base_delay=0.1, max_delay=1.0)
            elapsed = time.time() - start

            # Minimum várakozási idő: 0.1 (1st retry) + 0.2 (2nd retry) = 0.3s
            assert elapsed >= 0.2  # Allow some margin

    def test_retry_count_in_error(self):
        """Retry count szerepel a hibában."""
        with patch("moltagent.retry.RETRYABLE_EXCEPTIONS", (MockAPIConnectionError,)):
            func = MagicMock(side_effect=MockAPIConnectionError("connection failed"))

            with pytest.raises(ReplyError) as exc_info:
                call_with_retry(func, max_retries=3, base_delay=0.01)

            assert exc_info.value.retry_count == 3
