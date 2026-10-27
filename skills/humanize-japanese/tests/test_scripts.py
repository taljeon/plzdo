from pathlib import Path
import re
import subprocess
import sys

import pytest


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_script(script, before, after, *options):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--before", str(before),
         "--after", str(after), *options],
        capture_output=True,
        text=True,
        check=False,
    )


def write_pair(tmp_path, before, after):
    paths = tmp_path / "before.txt", tmp_path / "after.txt"
    paths[0].write_text(before, encoding="utf-8")
    paths[1].write_text(after, encoding="utf-8")
    return paths


@pytest.mark.parametrize(
    "before,after,code,percentage",
    [
        ("調査対象は学生である。", "調査対象は学生である。", 0, "0.0%"),
        ("あいうえおかきくけこ", "あいうえおかきくけさ", 0, "10.0%"),
        ("あいうえおかきくけこ", "あいうえおかきさしす", 1, "30.0%"),
        ("あいうえおかきくけこ", "あいうえおかさしすせ", 1, "40.0%"),
        ("あいうえおかきくけこ", "あいうえおさしすせそ", 2, "50.0%"),
        ("調査対象は学生である。", "カタカナ", 2, "100.0%"),
        ("", "", 0, "0.0%"),
        ("", "調査", 2, "100.0%"),
    ],
)
def test_change_rate_thresholds(tmp_path, before, after, code, percentage):
    result = run_script("change_rate.py", *write_pair(tmp_path, before, after))
    assert result.returncode == code, result.stderr
    assert result.stdout.strip() == percentage


@pytest.mark.parametrize("missing", ["before", "after"])
def test_change_rate_missing_file(tmp_path, missing):
    before, after = write_pair(tmp_path, "資料を確認する。", "資料を確認する。")
    (before if missing == "before" else after).unlink()
    result = run_script("change_rate.py", before, after)
    assert result.returncode == 3
    assert "Cannot read input" in result.stderr


def test_change_rate_does_not_discard_repeated_japanese(tmp_path):
    before, after = write_pair(tmp_path, "あ" * 300 + "い" * 300,
                              "あ" * 300 + "う" * 60 + "い" * 240)
    result = run_script("change_rate.py", before, after)
    assert result.returncode == 0
    assert result.stdout.strip() == "10.0%"


def test_change_rate_compares_raw_line_endings(tmp_path):
    before, after = tmp_path / "before.txt", tmp_path / "after.txt"
    before.write_bytes("資料\r\n".encode("utf-8"))
    after.write_bytes("資料\n".encode("utf-8"))
    result = run_script("change_rate.py", before, after)
    assert result.returncode == 0
    assert result.stdout.strip() == "14.3%"


def test_ignore_markup(tmp_path):
    before = (
        "## 調査概要\n- 費用を確認する。\n* 日程を確認する。\n+ 担当を確認する。\n"
        "1. 資料を読む。\n2) 結果を記録する。\n> > 課題を整理する。\n"
        "```text\nコード内の資料\n```\n~~~\n別の資料\n~~~\n"
        "---\n* * *\n___\n| 項目 | 結果 |\n| :--- | ---: |\n| 費用 | 同じ |\n"
    )
    after = (
        "調査概要\n費用を確認する。\n日程を確認する。\n担当を確認する。\n"
        "資料を読む。\n結果を記録する。\n課題を整理する。\n"
        "コード内の資料\n別の資料\n| 項目 | 結果 |\n| 費用 | 同じ |\n"
    )
    paths = write_pair(tmp_path, before, after)
    raw = run_script("change_rate.py", *paths)
    filtered = run_script("change_rate.py", *paths, "--ignore-markup")
    assert raw.stdout.strip() != "0.0%"
    assert filtered.returncode == 0
    assert filtered.stdout.strip() == "0.0%"


def test_ignore_markup_keeps_code_contents_and_table_data(tmp_path):
    paths = write_pair(tmp_path, "```\n資料甲\n```\n|甲|甲|", "資料乙\n|乙|乙|")
    result = run_script("change_rate.py", *paths, "--ignore-markup")
    assert result.stdout.strip() != "0.0%"


def test_ignore_markup_keeps_content_numbers(tmp_path):
    paths = write_pair(tmp_path, "# 2026年の調査\n１． 12人が回答した。", "2026年の調査\n12人が回答した。")
    result = run_script("change_rate.py", *paths, "--ignore-markup")
    assert result.returncode == 0
    assert result.stdout.strip() == "0.0%"


@pytest.mark.parametrize(
    "before,after,category,removed,added",
    [
        ("参加者は10人である。", "参加者は11人である。", "digit runs", "10", "11"),
        ("題名は「学内調査」である。", "題名は「学外調査」である。", "quoted spans", "「学内調査」", "「学外調査」"),
        ("『調査報告』を読む。", "『調査結果』を読む。", "quoted spans", "『調査報告』", "『調査結果』"),
        ("APIを確認する。", "SDKを確認する。", "ASCII words", "API", "SDK"),
        ("APIを確認する。", "apiを確認する。", "ASCII words", "API", "api"),
    ],
)
def test_check_preserved_reports_changed_items(tmp_path, before, after, category, removed, added):
    result = run_script("check_preserved.py", *write_pair(tmp_path, before, after))
    assert result.returncode == 1
    assert f"{category}: removed {removed!r} (count: 1)" in result.stdout
    assert f"{category}: added {added!r} (count: 1)" in result.stdout


@pytest.mark.parametrize("text", ["10人、10人", "「調査」「調査」", "APIとAPI"])
def test_check_preserved_checks_multiplicity(tmp_path, text):
    after = {"10人、10人": "10人", "「調査」「調査」": "「調査」", "APIとAPI": "API"}[text]
    result = run_script("check_preserved.py", *write_pair(tmp_path, text, after))
    assert result.returncode == 1
    assert "removed" in result.stdout
    assert "count: 1" in result.stdout


def test_check_preserved_normalizes_only_digit_runs(tmp_path):
    paths = write_pair(tmp_path, "参加者は１２人、回答者は3人である。", "参加者は12人、回答者は３人である。")
    result = run_script("check_preserved.py", *paths)
    assert result.returncode == 0, result.stdout


def test_check_preserved_keeps_quoted_digit_typography(tmp_path):
    result = run_script("check_preserved.py", *write_pair(tmp_path, "「１２人」", "「12人」"))
    assert result.returncode == 1
    assert "quoted spans" in result.stdout
    assert "digit runs" not in result.stdout


def test_check_preserved_checks_nested_quotations(tmp_path):
    result = run_script("check_preserved.py", *write_pair(tmp_path, "「『資料』を読む」", "『資料』を読む"))
    assert result.returncode == 1
    assert "「『資料』を読む」" in result.stdout
    assert "removed '『資料』'" not in result.stdout


def test_check_preserved_passes_clean_rewrite(tmp_path):
    paths = write_pair(tmp_path, "2026年、APIを通じて「回答」を取得する。",
                       "2026年、APIで「回答」を取得する。")
    result = run_script("check_preserved.py", *paths)
    assert result.returncode == 0, result.stdout
    assert result.stdout.strip() == "All tracked items are preserved."


@pytest.mark.parametrize("genre", ["report", "mail", "document", "readme", "blog"])
def test_genre_fixtures_pass_both_scripts(genre):
    before = FIXTURES / genre / "input.txt"
    after = FIXTURES / genre / "good_output.txt"
    for script in ("change_rate.py", "check_preserved.py"):
        result = run_script(script, before, after)
        assert result.returncode == 0, f"{genre}: {script}: {result.stdout}{result.stderr}"


def test_readme_fixture_keeps_code_verbatim():
    # Both scripts pass even if a code comment or URL changes, so check README code exactly.
    before = (FIXTURES / "readme" / "input.txt").read_text(encoding="utf-8")
    after = (FIXTURES / "readme" / "good_output.txt").read_text(encoding="utf-8")
    spans = re.findall(r"```.*?```|`[^`\n]+`|https?://\S+", before, re.S)
    assert len(spans) == 5
    for span in spans:
        assert span in after, span
