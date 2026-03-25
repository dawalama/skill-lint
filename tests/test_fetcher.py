"""Tests for remote fetcher — tests URL parsing without making real network calls."""

from skill_audit.fetcher import is_remote


class TestIsRemote:
    def test_https_url(self):
        assert is_remote("https://github.com/user/repo") is True

    def test_http_url(self):
        assert is_remote("http://example.com/skill.md") is True

    def test_local_path(self):
        assert is_remote("/home/user/.ai/skills/review.md") is False

    def test_relative_path(self):
        assert is_remote("./skills/review.md") is False

    def test_home_path(self):
        assert is_remote("~/skills/review.md") is False
