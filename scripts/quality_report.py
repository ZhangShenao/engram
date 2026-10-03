"""Run coverage, duplication, and lint gates, then write reports/quality.md.

Exit status is non-zero when pytest fails, statement coverage is under
COVERAGE_MIN, duplicated lines are over DUPLICATION_MAX, or ruff reports
lint issues or unformatted files.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
COVERAGE_MIN = 65
DUPLICATION_MAX = 5
COV_SOURCES = [
    "packages/engram_contracts/engram_contracts",
    "services/character/character_service",
    "services/conversation/conversation_service",
    "services/gateway/gateway_service",
    "services/harness/harness_service",
    "services/memory/memory_service",
]


def _rel(path: str) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(ROOT))
    except ValueError:
        text = str(candidate)
        marker = f"{ROOT.name}/"
        if marker in text:
            return text.split(marker, 1)[1]
        return text


def _run_pytest() -> int:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--junitxml",
        str(REPORTS / "junit.xml"),
        "-q",
        "--tb=line",
    ]
    for source in COV_SOURCES:
        command.extend(["--cov", source])
    command.extend(
        [
            "--cov-report=term-missing",
            f"--cov-report=json:{REPORTS / 'coverage.json'}",
            f"--cov-fail-under={COVERAGE_MIN}",
        ]
    )
    return subprocess.run(command, cwd=ROOT).returncode


def _run_ruff() -> tuple[int | None, int | None, list[str]]:
    """Return (lint issues, unformatted files, sample lines); None means ruff did not run."""
    check = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format", "json", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    issues: int | None = None
    lines: list[str] = []
    if check.returncode in (0, 1):
        findings = json.loads(check.stdout or "[]")
        issues = len(findings)
        for item in findings:
            location = item.get("location") or {}
            lines.append(
                f"- `{_rel(item.get('filename', ''))}:{location.get('row', '?')}` "
                f"{item.get('code') or ''} {item.get('message', '')}".rstrip()
            )
    else:
        print(check.stderr, file=sys.stderr)

    fmt = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    unformatted: int | None = None
    if fmt.returncode in (0, 1):
        pending = [
            line.removeprefix("Would reformat: ").strip()
            for line in fmt.stdout.splitlines()
            if line.startswith("Would reformat: ")
        ]
        unformatted = len(pending)
        lines.extend(f"- `{_rel(path)}` 需要 `ruff format`" for path in pending)
    else:
        print(fmt.stderr, file=sys.stderr)

    for line in lines:
        print(line)
    return issues, unformatted, lines


def _run_jscpd() -> int:
    command = [
        "npx",
        "--yes",
        "jscpd@4.0.5",
        "--config",
        ".jscpd.json",
        "--pattern",
        "**/*.{py,ts,tsx}",
        "services",
        "packages",
        "web/src",
    ]
    return subprocess.run(command, cwd=ROOT).returncode


def _coverage() -> tuple[float | None, list[tuple[str, float, int]]]:
    path = REPORTS / "coverage.json"
    if not path.is_file():
        return None, []
    payload = json.loads(path.read_text())
    percent = payload.get("totals", {}).get("percent_covered")
    rows: list[tuple[str, float, int]] = []
    for name, info in payload.get("files", {}).items():
        summary = info.get("summary", {})
        statements = int(summary.get("num_statements") or 0)
        if statements == 0:
            continue
        rows.append((_rel(name), float(summary.get("percent_covered") or 0), statements))
    rows.sort(key=lambda item: (item[1], -item[2], item[0]))
    return (None if percent is None else float(percent)), rows


def _tests() -> tuple[bool | None, str]:
    path = REPORTS / "junit.xml"
    if not path.is_file():
        return None, "没有测试结果"
    suite = ET.parse(path).getroot()
    suites = [suite] if suite.tag == "testsuite" else list(suite.findall("testsuite"))
    tests = failures = errors = skipped = 0
    for item in suites:
        tests += int(item.attrib.get("tests", 0))
        failures += int(item.attrib.get("failures", 0))
        errors += int(item.attrib.get("errors", 0))
        skipped += int(item.attrib.get("skipped", 0))
    passed = tests - failures - errors - skipped
    return failures + errors == 0, (
        f"{passed} 通过，{failures} 失败，{errors} 错误，{skipped} 跳过，共 {tests}"
    )


def _clone_location(side: dict) -> str:
    line = side.get("startLoc", {}).get("line", side.get("start", ""))
    return f"{_rel(side.get('name', ''))}:{line}"


def _duplicates() -> tuple[float | None, int, list[str]]:
    path = REPORTS / "jscpd" / "jscpd-report.json"
    if not path.is_file():
        return None, 0, []
    payload = json.loads(path.read_text())
    total = payload.get("statistics", {}).get("total", {})
    percent = total.get("percentage")
    clones = int(total.get("clones") or 0)
    lines: list[str] = []
    for item in payload.get("duplicates", [])[:8]:
        first = item.get("firstFile", {})
        second = item.get("secondFile", {})
        left = _clone_location(first)
        right = _clone_location(second)
        lines.append(f"- {item.get('lines', '?')} 行：`{left}` 与 `{right}`")
    return (None if percent is None else float(percent)), clones, lines


def _status(ok: bool) -> str:
    return "通过" if ok else "未通过"


def _write(
    pytest_code: int,
    jscpd_code: int,
    ruff_result: tuple[int | None, int | None, list[str]],
) -> int:
    lint_issues, unformatted, lint_lines = ruff_result
    lint_ok = lint_issues == 0 and unformatted == 0
    if lint_issues is None or unformatted is None:
        lint_text = "ruff 没有运行"
    else:
        lint_text = f"{lint_issues} 处 lint 问题，{unformatted} 个文件未格式化"
    lint_block = "\n".join(lint_lines[:8]) if lint_lines else "- 没有 lint 或格式问题"
    percent, files = _coverage()
    tests_ok, tests_text = _tests()
    duplication, clones, clone_lines = _duplicates()
    coverage_ok = percent is not None and percent + 1e-9 >= COVERAGE_MIN
    duplication_within = duplication is not None and duplication <= DUPLICATION_MAX
    duplication_ok = duplication_within and jscpd_code == 0
    coverage_text = "没有覆盖率结果" if percent is None else f"{percent:.1f}%"
    if duplication is None:
        duplication_text = "没有重复度结果"
    else:
        duplication_text = f"{duplication:.2f}%（{clones} 处）"

    lowest = [row for row in files if row[1] < 100][:8]
    lowest_lines = [
        f"- `{name}` {covered:.0f}%（{statements} 条语句）" for name, covered, statements in lowest
    ] or ["- 没有低于 100% 的文件"]
    clone_block = "\n".join(clone_lines) if clone_lines else "- 没有达到最小长度的重复片段"

    report = f"""## 工程质量报告

| 检查 | 结果 | 当前 | 门禁 |
|------|------|------|------|
| 单元测试 | {_status(tests_ok is True)} | {tests_text} | 全部通过 |
| 语句覆盖率 | {_status(coverage_ok)} | {coverage_text} | ≥ {COVERAGE_MIN}% |
| 代码重复率 | {_status(duplication_within)} | {duplication_text} | ≤ {DUPLICATION_MAX}% |
| 代码规范 | {_status(lint_ok)} | {lint_text} | 0 处问题，全部已格式化 |

覆盖率按语句统计，范围是五个服务和 `engram_contracts`。\
重复率用 jscpd，至少 8 行、50 个 token 才算一处，范围是 `services/`、`packages/` 和 `web/src`。\
代码规范用 `ruff check` 和 `ruff format --check`，配置在 `pyproject.toml`。

### 代码规范问题

{lint_block}

### 覆盖率最低的文件

{chr(10).join(lowest_lines)}

### 重复片段

{clone_block}
"""
    (REPORTS / "quality.md").write_text(report)
    print(report)
    if (
        tests_ok is not True
        or not coverage_ok
        or not duplication_ok
        or not lint_ok
        or pytest_code != 0
        or jscpd_code != 0
    ):
        return 1
    return 0


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    pytest_code = _run_pytest()
    jscpd_code = _run_jscpd()
    ruff_result = _run_ruff()
    return _write(pytest_code, jscpd_code, ruff_result)


if __name__ == "__main__":
    sys.exit(main())
