"""
CUBE resources: router memory/CPU status and running-config vs. template.

Registers two ResourceSpecs, service "CUBE":

  cube.memory          one Item per memory/CPU metric from
                       'show platform software status control-processor br'
  cube.config_sections one Item per running-config section compared
                       against the voice config template

Both providers open their own SSH session per fetch via
gui.backend.connections.cube_session(ctx.scope) and always close it in a
finally block, because CUBE has no cached client (see connections.py:
get_client() refuses CUBE targets on purpose).

Ground truth for the show commands, parsing and thresholds is
cube/check_router_mem_status.py and cube/compare_router_config.py. Both
scripts exit the process at import time when netmiko is missing
(sys.exit(1) at module scope) and call get_object_for_single_operation() /
input() as part of their normal flow, so importing them directly from a web
server is not safe. The parsing logic below is therefore reimplemented here,
each function's docstring says which script function it mirrors, and the
two copies must be kept in step by hand if the script changes.

Customer variables (read non-interactively; setup/var_loader.py prompts
interactively and would hang a web request, so it is NOT used here):

  check_router_mem_status.var [variables]
    low_memory_threshold = 33   (int, percent free memory before a row is
                                 flagged; matches the script's own default)

  compare_router_config.var [variables]
    template_path = <repo>/_DATA/router_config_template.txt
                                 (the script itself has no .var file yet -
                                 it just prompts for a path at the terminal
                                 with this same default. There is no
                                 .var.EXAMPLE for it in .var/examples/; if
                                 one is added later, add "template_path" to
                                 its [variables] section and this default
                                 stays the fallback.)

Both values can be overridden per sync through spec.filters, which the
frontend renders as inputs above the table (ctx.params).

Guesses / things that could not be checked against a live device:
  - The exact column layout of 'show platform software status
    control-processor br' varies by IOS-XE platform and version. The memory
    parser handles the common "Label  Total  Used (Pct)  Free (Pct)
    [Committed (Pct)]" row shape (Processor, RPn, and an IO memory row such
    as "RP0 (IOmem)"); anything that doesn't match that shape is skipped
    rather than raising.
  - The task asks for "CPU 5-sec/1-min/5-min" metrics. This command's CPU
    section is not parsed by check_router_mem_status.py at all (it only
    ever looks at the Memory (kB) block), so there is no script logic to
    mirror for CPU. _parse_cpu_metrics() first looks for the classic
    "CPU utilization for five seconds: X%; one minute: Y%; five minutes: Z%"
    line, and otherwise falls back to reading whatever per-slot
    Min/Sec-headed table it finds (e.g. a "Load Average" or "CPU
    Utilization" section). If neither shape is present, no CPU metrics are
    produced - the memory metrics still are.
  - No threshold is meaningful for CPU or for total/used/committed memory
    values, so those rows are always status "ok"; only a *_free metric is
    compared against low_memory_threshold.
"""

from __future__ import annotations

import configparser
import re
from datetime import datetime
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from gui.backend import connections
from gui.backend.resources.registry import register
from gui.backend.resources.types import (
    Action, Column, Context, Field, Item, ResourceSpec,
)

ROOT = Path(__file__).resolve().parents[4]

# -- customer variables (.var files), read non-interactively --------------

DEFAULT_LOW_MEMORY_THRESHOLD = 33
DEFAULT_TEMPLATE_PATH = ROOT / "_DATA" / "router_config_template.txt"


def _read_var(script_stem: str, key: str, default: str) -> str:
    """Read one key from .var/<script_stem>.var [variables], never prompting.

    Missing file, missing section, missing key or a malformed file all fall
    back to `default` quietly - this runs inside a web request, so there is
    nowhere to show a prompt and nothing should be printed or logged.
    """
    path = ROOT / ".var" / f"{script_stem}.var"
    if not path.is_file():
        return default
    cfg = configparser.ConfigParser()
    try:
        cfg.read(path)
    except configparser.Error:
        return default
    if not cfg.has_section("variables"):
        return default
    return cfg.get("variables", key, fallback=default)


def _threshold(ctx: Context) -> int:
    """low_memory_threshold: ctx.params override, then .var, then default."""
    override = (ctx.params or {}).get("low_memory_threshold")
    if override not in (None, ""):
        try:
            return int(float(override))
        except (TypeError, ValueError):
            pass
    raw = _read_var("check_router_mem_status", "low_memory_threshold",
                    str(DEFAULT_LOW_MEMORY_THRESHOLD))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_LOW_MEMORY_THRESHOLD


def _template_path(ctx: Context) -> str:
    """template_path: ctx.params override, then .var, then the script's own default."""
    override = (ctx.params or {}).get("template_path")
    if override:
        return override.strip()
    return _read_var("compare_router_config", "template_path", str(DEFAULT_TEMPLATE_PATH))


# ===========================================================================
# cube.memory
# ===========================================================================

_MEM_COMMAND = "show platform software status control-processor br"

_ROW_RE = re.compile(
    r'^\s*(?P<label>[A-Za-z0-9_/().\-]+(?:\s+[A-Za-z0-9_/().\-]+)*?)\s+'
    r'(?P<total>\d+)\s+'
    r'(?P<used>\d+)\s*\(\s*(?P<used_pct>\d+)\s*%\s*\)\s+'
    r'(?P<free>\d+)\s*\(\s*(?P<free_pct>\d+)\s*%\s*\)'
    r'(?:\s+(?P<committed>\d+)\s*\(\s*(?P<committed_pct>\d+)\s*%\s*\))?'
    r'\s*$'
)

_CPU_LINE_RE = re.compile(
    r'CPU\s+utilization\s+for\s+five\s+seconds.*?(?P<five_sec>\d+)\s*%.*?'
    r'one\s+minute.*?(?P<one_min>\d+)\s*%.*?'
    r'five\s+minutes.*?(?P<five_min>\d+)\s*%',
    re.IGNORECASE | re.DOTALL,
)


def _extract_memory_block(output: str) -> str:
    """Ported from cube/check_router_mem_status.py extract_memory_section().

    Keep this in step with that function if the script's parsing changes.
    """
    lines = output.split('\n')
    memory_lines: List[str] = []
    in_memory = False
    for line in lines:
        if 'Memory (kB)' in line:
            in_memory = True
        if in_memory:
            memory_lines.append(line)
            if len(memory_lines) > 1 and line.strip() and not line[0].isspace():
                if 'Memory' not in line:
                    memory_lines.pop()
                    break
    return '\n'.join(memory_lines)


def _iter_memory_rows(block: str):
    """Yield (label, total, used, used_pct, free, free_pct, committed, committed_pct)
    for each data row of the Memory (kB) table; header/unmatched lines are skipped.
    """
    for line in block.split('\n'):
        if 'Total' in line and ('Used' in line or 'Free' in line):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        gd = m.groupdict()
        yield (
            gd['label'].strip(), gd['total'], gd['used'], gd['used_pct'],
            gd['free'], gd['free_pct'], gd.get('committed'), gd.get('committed_pct'),
        )


def _metric_prefix(label: str) -> str:
    norm = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')
    return norm or "unknown"


def _to_number(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _free_status(pct, threshold: int) -> str:
    pct_val = _to_number(pct)
    if pct_val is None:
        return "warn"
    if pct_val < threshold:
        return "danger"
    if pct_val < threshold + 10:
        return "warn"
    return "ok"


def _metric_item(key: str, value, unit: str, pct, status: str) -> Item:
    value_num = _to_number(value)
    return Item(key=key, fields={
        "value": value_num if value_num is not None else value,
        "unit": unit,
        "percentage": _to_number(pct),
        "status": status,
    })


def _parse_cpu_metrics(output: str) -> List[Tuple[str, str, str]]:
    """Best-effort CPU metrics; see the module docstring's "Guesses" section."""
    m = _CPU_LINE_RE.search(output)
    if m:
        return [
            ("cpu_5sec", m.group("five_sec"), "%"),
            ("cpu_1min", m.group("one_min"), "%"),
            ("cpu_5min", m.group("five_min"), "%"),
        ]

    metrics: List[Tuple[str, str, str]] = []
    lines = output.split('\n')
    for i, line in enumerate(lines):
        header_tokens = re.findall(r'\d+-(?:Min|Sec)', line, re.IGNORECASE)
        if not header_tokens:
            continue
        for data_line in lines[i + 1:i + 6]:
            tokens = data_line.split()
            if len(tokens) < 2:
                continue
            nums = [t.rstrip('%') for t in tokens[1:] if re.match(r'^\d+(\.\d+)?%?$', t)]
            if not nums:
                continue
            slot = re.sub(r'[^a-z0-9]+', '_', tokens[0].lower()).strip('_') or "slot"
            for label, val in zip(header_tokens, nums):
                key = "cpu_" + slot + "_" + re.sub(r'[^a-z0-9]+', '', label.lower())
                metrics.append((key, val, "%"))
        break
    return metrics


def _memory_items(output: str, threshold: int) -> List[Item]:
    items: List[Item] = []
    block = _extract_memory_block(output)
    for label, total, used, used_pct, free, free_pct, committed, committed_pct in _iter_memory_rows(block):
        prefix = _metric_prefix(label)
        if total is not None:
            items.append(_metric_item(f"{prefix}_total", total, "kB", None, "ok"))
        if used is not None:
            items.append(_metric_item(f"{prefix}_used", used, "kB", used_pct, "ok"))
        if free is not None:
            items.append(_metric_item(f"{prefix}_free", free, "kB", free_pct,
                                      _free_status(free_pct, threshold)))
        if committed is not None:
            items.append(_metric_item(f"{prefix}_committed", committed, "kB",
                                      committed_pct, "ok"))

    try:
        for key, val, unit in _parse_cpu_metrics(output):
            items.append(_metric_item(key, val, unit, None, "ok"))
    except Exception:
        pass  # CPU parsing is a bonus; never let it break the memory rows

    if not items:
        items.append(_metric_item("memory_status", "", "", None, "warn"))
    return items


def _fetch_memory(ctx: Context) -> List[Item]:
    threshold = _threshold(ctx)
    conn = connections.cube_session(ctx.scope)
    try:
        output = conn.send_command(_MEM_COMMAND)
    finally:
        conn.disconnect()

    try:
        return _memory_items(output, threshold)
    except Exception:
        # Parsing must never fail a sync; surface one row instead.
        return [_metric_item("memory_status", "", "", None, "warn")]


MEMORY_COLUMNS = (
    Column("value", "Value", kind="number"),
    Column("unit", "Unit", kind="text"),
    Column("percentage", "Percent", kind="number"),
    Column("status", "Status", kind="badge",
           tone_map={"ok": "ok", "warn": "warn", "danger": "danger"}),
)

MEMORY_FILTERS = (
    Field(name="low_memory_threshold", label="Low free memory threshold (%)",
          kind="number", default=str(DEFAULT_LOW_MEMORY_THRESHOLD),
          help="A *_free row below this percent free is flagged warn/danger. "
               "Falls back to .var/check_router_mem_status.var "
               "[variables] low_memory_threshold, then 33."),
)

register(ResourceSpec(
    id="cube.memory",
    service="CUBE",
    label="Router Memory Status",
    key_label="Metric",
    description="Processor/IO memory and CPU load from "
                "'show platform software status control-processor br'.",
    columns=MEMORY_COLUMNS,
    fetch=_fetch_memory,
    filters=MEMORY_FILTERS,
    sync_note="Opens its own SSH session per sync; CUBE has no cached client.",
))


# ===========================================================================
# cube.config_sections
# ===========================================================================

_RUNNING_CONFIG_COMMAND = "show running-config"

_VOICE_KEYWORDS = (
    'voice', 'dial-peer', 'call-manager', 'ephone', 'telephony-service',
    'gateway', 'h323', 'mgcp', 'sccp', 'sip', 'isdn', 'primary-rate', 'bri',
    'ds0', 'voice-port', 'connection', 'pots', 'fax', 'codec', 'class provider',
)


def _parse_config_sections(config_text: str) -> Dict[str, List[str]]:
    """Ported from cube/compare_router_config.py ConfigParser.parse_sections()
    and ConfigParser.extract_voice_sections(). Keep this in step with those
    if the script's parsing changes.
    """
    sections: Dict[str, List[str]] = {}
    current_section = None
    current_lines: List[str] = []

    for line in config_text.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('!'):
            continue
        if line and not line[0].isspace():
            if current_section:
                sections[current_section] = current_lines
            current_section = stripped
            current_lines = [stripped]
        elif current_section:
            current_lines.append(line.rstrip())
    if current_section:
        sections[current_section] = current_lines

    voice_sections = {}
    for name, lines in sections.items():
        if any(k in name.lower() for k in _VOICE_KEYWORDS):
            voice_sections[name] = lines
    return voice_sections


def _normalize_lines(lines: List[str]) -> List[str]:
    return [l.rstrip() for l in lines if l.strip()]


def _compare_sections(template_sections: Dict[str, List[str]],
                      router_sections: Dict[str, List[str]]) -> Dict[str, dict]:
    """Adapted from ConfigComparator.compare()/_compute_diff() in
    cube/compare_router_config.py, flattened into one dict per section
    instead of the script's separate missing/extra/diffs lists.
    """
    results: Dict[str, dict] = {}

    for name, lines in template_sections.items():
        if name not in router_sections:
            results[name] = {"status": "missing",
                              "missing_lines": _normalize_lines(lines),
                              "extra_lines": []}
            continue
        t_lines = _normalize_lines(lines)
        r_lines = _normalize_lines(router_sections[name])
        if t_lines == r_lines:
            results[name] = {"status": "match", "missing_lines": [], "extra_lines": []}
            continue
        sm = SequenceMatcher(None, t_lines, r_lines)
        template_only: List[str] = []
        router_only: List[str] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ('delete', 'replace'):
                template_only.extend(t_lines[i1:i2])
            if tag in ('insert', 'replace'):
                router_only.extend(r_lines[j1:j2])
        results[name] = {"status": "differs", "missing_lines": template_only,
                          "extra_lines": router_only}

    for name, lines in router_sections.items():
        if name not in template_sections:
            results[name] = {"status": "extra", "missing_lines": [],
                              "extra_lines": _normalize_lines(lines)}

    return results


def _section_item(name: str, comparison: dict) -> Item:
    diff_lines = ([f"- {l}" for l in comparison["missing_lines"]] +
                  [f"+ {l}" for l in comparison["extra_lines"]])
    shown = diff_lines[:10]
    more = f"+{len(diff_lines) - 10} more" if len(diff_lines) > 10 else ""
    return Item(key=name, fields={
        "status": comparison["status"],
        "missing_count": len(comparison["missing_lines"]),
        "extra_count": len(comparison["extra_lines"]),
        "diff_lines": shown,
        "more": more,
    })


def _fetch_config_sections(ctx: Context) -> List[Item]:
    template_path = _template_path(ctx)
    try:
        template_text = Path(template_path).read_text()
    except OSError as exc:
        raise ValueError(f"Could not read template {template_path!r}: {exc}") from exc
    template_sections = _parse_config_sections(template_text)

    conn = connections.cube_session(ctx.scope)
    try:
        output = conn.send_command(_RUNNING_CONFIG_COMMAND)
    finally:
        conn.disconnect()

    router_sections = _parse_config_sections(output)
    comparison = _compare_sections(template_sections, router_sections)
    return [_section_item(name, comparison[name]) for name in sorted(comparison)]


def _render_html_report(hostname: str, template_sections: Dict[str, List[str]],
                        comparison: Dict[str, dict]) -> str:
    """Adapted from generate_html_report() in cube/compare_router_config.py.
    Keep the look of this in step with that function if it changes.
    """
    missing_sections = sorted(n for n, c in comparison.items() if c["status"] == "missing")
    extra_sections = sorted(n for n, c in comparison.items() if c["status"] == "extra")
    diff_sections = sorted(n for n, c in comparison.items() if c["status"] == "differs")
    has_variances = bool(missing_sections or extra_sections or diff_sections)

    status_color = '#dc3545' if has_variances else '#28a745'
    status_text = 'VARIANCES FOUND' if has_variances else 'COMPLIANT'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Config Comparison Report - {escape(hostname)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .header {{ background-color: {status_color}; color: white; padding: 20px; border-radius: 5px; }}
        .header h1 {{ margin: 0; }}
        .status {{ font-size: 24px; font-weight: bold; }}
        .timestamp {{ font-size: 12px; margin-top: 10px; }}
        .section {{ background-color: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .section-title {{ background-color: #007bff; color: white; padding: 10px; border-radius: 3px; font-weight: bold; }}
        .variance-type {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 10px; margin: 10px 0; border-radius: 3px; }}
        .missing {{ background-color: #f8d7da; border-left: 4px solid #dc3545; }}
        .extra {{ background-color: #d1ecf1; border-left: 4px solid #17a2b8; }}
        .compliant {{ background-color: #d4edda; border-left: 4px solid #28a745; }}
        .code {{ background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 3px; padding: 10px; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; }}
        .line {{ margin: 3px 0; }}
        .template-only {{ color: #dc3545; }}
        .router-only {{ color: #17a2b8; }}
        .label {{ font-weight: bold; font-size: 12px; text-transform: uppercase; }}
        .summary {{ background-color: #e7f3ff; border-left: 4px solid #2196F3; padding: 15px; border-radius: 3px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Router Configuration Comparison Report</h1>
        <div class="status">{status_text}</div>
        <div>Router: {escape(hostname)}</div>
        <div class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>

    <div class="section">
        <div class="summary">
            <div><strong>Template Sections Checked:</strong> {len(template_sections)}</div>
            <div><strong>Missing Sections:</strong> {len(missing_sections)}</div>
            <div><strong>Extra Sections:</strong> {len(extra_sections)}</div>
            <div><strong>Sections with Differences:</strong> {len(diff_sections)}</div>
        </div>
    </div>
"""

    if missing_sections:
        html += '<div class="section">'
        html += '<div class="section-title">Missing Sections (in template but not in router config)</div>'
        for section in missing_sections:
            html += f'<div class="variance-type missing">{escape(section)}</div>'
        html += '</div>'

    if extra_sections:
        html += '<div class="section">'
        html += '<div class="section-title">Extra Sections (in router config but not in template)</div>'
        for section in extra_sections:
            html += f'<div class="variance-type extra">{escape(section)}</div>'
        html += '</div>'

    for section_name in diff_sections:
        diff = comparison[section_name]
        html += '<div class="section">'
        html += f'<div class="section-title">{escape(section_name)}</div>'
        html += '<div style="margin-top: 10px;">'

        if diff["missing_lines"]:
            html += '<div class="variance-type missing"><span class="label">In Template Only (Missing from Router)</span>'
            html += '<div class="code">'
            for line in diff["missing_lines"]:
                html += f'<div class="line template-only">- {escape(line)}</div>'
            html += '</div></div>'

        if diff["extra_lines"]:
            html += '<div class="variance-type extra"><span class="label">In Router Only (Extra in Router)</span>'
            html += '<div class="code">'
            for line in diff["extra_lines"]:
                html += f'<div class="line router-only">+ {escape(line)}</div>'
            html += '</div></div>'

        html += '</div></div>'

    if not has_variances:
        html += '<div class="section"><div class="variance-type compliant"><strong>Configuration is compliant with template</strong></div></div>'

    html += """
</body>
</html>
"""
    return html


def _export_config_report(ctx: Context, _item: Optional[dict]):
    """Re-run the comparison and write the HTML report, same as
    cube/compare_router_config.py's generate_html_report()/process_single_router().
    """
    template_path = _template_path(ctx)
    try:
        template_text = Path(template_path).read_text()
    except OSError as exc:
        return False, f"Could not read template {template_path!r}: {exc}"
    template_sections = _parse_config_sections(template_text)

    try:
        conn = connections.cube_session(ctx.scope)
    except Exception as exc:
        return False, f"Could not open SSH session to {ctx.scope}: {exc}"
    try:
        output = conn.send_command(_RUNNING_CONFIG_COMMAND)
    except Exception as exc:
        return False, f"Could not read running-config from {ctx.scope}: {exc}"
    finally:
        conn.disconnect()

    router_sections = _parse_config_sections(output)
    comparison = _compare_sections(template_sections, router_sections)
    html = _render_html_report(ctx.scope, template_sections, comparison)

    reports_dir = ROOT / "_DATA" / "reports"
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_path = reports_dir / f"{stamp}-{ctx.scope}_comparison.html"
        out_path.write_text(html)
    except OSError as exc:
        return False, f"Could not write report: {exc}"
    return True, f"Report saved: {out_path.relative_to(ROOT)}"


CONFIG_COLUMNS = (
    Column("status", "Status", kind="badge",
           tone_map={"match": "ok", "differs": "warn", "missing": "danger", "extra": "info"}),
    Column("missing_count", "Missing Lines", kind="number"),
    Column("extra_count", "Extra Lines", kind="number"),
    Column("diff_lines", "Differences", kind="list"),
    Column("more", "More", kind="text", optional=True),
)

CONFIG_FILTERS = (
    Field(name="template_path", label="Template file path", kind="text", default="",
          placeholder=str(DEFAULT_TEMPLATE_PATH),
          help="Overrides .var/compare_router_config.var [variables] "
               "template_path for this sync only."),
)

CONFIG_ACTIONS = (
    Action(id="export", label="Export Comparison Report", handler=_export_config_report,
           scope_mode="none", style="secondary",
           help="Re-runs the comparison and writes the HTML report into "
                "_DATA/reports/, same as cube/compare_router_config.py."),
)

register(ResourceSpec(
    id="cube.config_sections",
    service="CUBE",
    label="Config Sections",
    key_label="Section",
    description="Running-config voice sections compared against the "
                "template, section by section.",
    columns=CONFIG_COLUMNS,
    fetch=_fetch_config_sections,
    filters=CONFIG_FILTERS,
    actions=CONFIG_ACTIONS,
    sync_note="Opens its own SSH session per sync; CUBE has no cached client.",
))
