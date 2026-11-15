"""TikTok chunk math (review fix 2): every chunk but the last is exactly
CHUNK, so the declared count must be ceil(size / CHUNK). No network, no
API calls — this only exercises the pure helper."""
import os
import sys

# Import as part of the platforms package (as scheduler.py loads it), so
# the module's relative `from ._http import ...` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from platforms.tiktok import CHUNK, chunk_count


def test_one_byte_is_one_chunk():
    assert chunk_count(1) == 1


def test_exactly_one_chunk_is_one_chunk():
    assert chunk_count(CHUNK) == 1


def test_one_byte_over_is_two_chunks():
    assert chunk_count(CHUNK + 1) == 2


def test_two_full_chunks_is_two_chunks():
    assert chunk_count(2 * CHUNK) == 2


def test_25mb_is_three_chunks():
    assert chunk_count(25 * 1024 * 1024) == 3
