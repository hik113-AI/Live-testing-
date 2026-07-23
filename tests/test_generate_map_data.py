"""Smoke tests for generate_map_data helper functions."""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from generate_map_data import in_malaysia, clean_coords, to_date_str, tier_idx, year_bucket


def test_in_malaysia_peninsular():
    assert in_malaysia(3.14, 101.69)   # KL


def test_in_malaysia_sarawak():
    assert in_malaysia(1.55, 110.35)   # Kuching


def test_in_malaysia_sabah():
    assert in_malaysia(5.98, 116.07)   # Kota Kinabalu


def test_in_malaysia_rejects_bangkok():
    assert not in_malaysia(13.75, 100.52)  # Bangkok, Thailand


def test_in_malaysia_rejects_sea():
    assert not in_malaysia(4.0, 107.0)  # South China Sea gap


def test_clean_coords_valid():
    lat, lon = clean_coords("3.14", "101.69")
    assert abs(lat - 3.14) < 0.01
    assert abs(lon - 101.69) < 0.01


def test_clean_coords_swapped():
    lat, lon = clean_coords("101.69", "3.14")
    assert abs(lat - 3.14) < 0.01


def test_clean_coords_invalid():
    assert clean_coords(None, None) == (None, None)
    assert clean_coords("0", "0") == (None, None)


def test_to_date_str_iso():
    assert to_date_str("2024-03-15") == "15 Mar 2024"


def test_to_date_str_already_formatted():
    assert to_date_str("14 Dec 2025") == "14 Dec 2025"


def test_to_date_str_empty():
    assert to_date_str("") == ""
    assert to_date_str(None) == ""


def test_tier_idx():
    assert tier_idx(250000) == 0   # under 300k
    assert tier_idx(450000) == 1   # 300k-600k
    assert tier_idx(800000) == 2   # 600k-1M
    assert tier_idx(1500000) == 3  # above 1M
    assert tier_idx(0) is None


def test_year_bucket():
    assert year_bucket("15 Mar 2024") == "2024"
    assert year_bucket("01 Jan 2020") == "≤2021"
    assert year_bucket("") == "n.d."
    assert year_bucket(None) == "n.d."
