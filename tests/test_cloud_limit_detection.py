def test_detects_status_and_quota_text():
    LIMIT_WORDS = ("quota", "credit", "limit", "insufficient")
    def is_limit_error(error):
        status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
        return status in {402, 429} or any(word in str(error).lower() for word in LIMIT_WORDS)

    class Response:
        status_code = 429
    class Error(Exception):
        response = Response()

    assert is_limit_error(Error())
    assert is_limit_error(RuntimeError("insufficient credits"))
    assert not is_limit_error(RuntimeError("connection reset"))