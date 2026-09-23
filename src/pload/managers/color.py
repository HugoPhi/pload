import os
import sys


class Colors:
    """Small color helper that stays quiet when output is redirected."""

    enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    @classmethod
    def _paint(cls, value, color):
        text = str(value)
        if not cls.enabled:
            return text
        return f"\033[1;{color}m{text}\033[0m"

    @classmethod
    def green(cls, value):
        return cls._paint(value, "32")

    @classmethod
    def red(cls, value):
        return cls._paint(value, "31")

    @classmethod
    def yellow(cls, value):
        return cls._paint(value, "33")

    @classmethod
    def cyan(cls, value):
        return cls._paint(value, "36")
