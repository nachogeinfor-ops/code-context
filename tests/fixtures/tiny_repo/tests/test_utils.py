from sample_app.utils import format_message, is_palindrome


def test_format_message():
    assert format_message("hi", "alice") == "Hi, alice!"


def test_is_palindrome():
    assert is_palindrome("racecar") is True
    assert is_palindrome("hello") is False
