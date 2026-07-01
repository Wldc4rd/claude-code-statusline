#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
#
# claude-code-statusline (personal build)
# Fork of github.com/Wldc4rd/claude-code-statusline (itself a fork of Servosity's).
# Two-line status line: model / account / cwd / git / time  +  context bar / rate-limit usage.
#
# This build ADDS two widgets to the upstream script, keeping its zero-dependency,
# single-file, uv-runnable, config-as-code ethos. All upstream behavior is preserved;
# the new widgets are opt-out via the CONFIG block below and degrade silently when
# their data is unavailable.
#
#   ADD 1  Active Claude account  -> reads ~/.claude.json oauthAccount EACH render so the
#          label updates the moment you switch accounts. Prints only a short human
#          label (never tokens/secrets/UUIDs).
#   ADD 2  Rate-limit usage       -> reads `rate_limits` from the statusline stdin payload
#          (Claude.ai Pro/Max only, populated after the first API response of a session)
#          and renders e.g. "wk 41%". No new dependency.
#
import sys
import json
import os
import subprocess
from datetime import datetime

# ============================ CONFIG (edit these) ============================
CONTEXT_WINDOW = 200_000          # context budget for the % bar. 1_000_000 for 1M-context tiers.

# --- ADD 1: active Claude account label -------------------------------------
SHOW_ACCOUNT = True               # show the active-account widget on line 1
ACCOUNT_ICON = "\U0001F464"       # 👤
# How to label the account. NOTE: if your accounts share a displayName AND email
# local-part (so neither distinguishes them), the email DOMAIN usually does — hence the
# default below. Examples use "user@example.com":
#   "email_domain" -> "example"            (label before the first dot of the domain)  [default]
#   "email_local"  -> "user"               (before the @)
#   "email"        -> "user@example.com"   (full address)
#   "display_name" -> oauthAccount.displayName
#   "org"          -> oauthAccount.organizationName
#   "smart"        -> org (if not auto-generated) else email_domain else email_local else display
ACCOUNT_MODE = "email_domain"
ACCOUNT_COLOR = "\033[94m"        # bright blue
ACCOUNT_MAXLEN = 18               # truncate labels longer than this

# --- ADD 2: rate-limit usage (from stdin `rate_limits`) ---------------------
SHOW_WEEKLY = True                # rate_limits.seven_day.used_percentage -> "wk NN%"
SHOW_FIVE_HOUR = False            # rate_limits.five_hour.used_percentage -> "5h NN%"
RATE_ICON = "\U0001F4CA"          # 📊  (prefixes the rate cluster; set "" to drop)
SHOW_WEEKLY_RESET = True          # append the weekly reset time -> "wk NN% ↻ Wed 7/1 2PM"
RESET_TZ = "America/Los_Angeles"  # timezone for the reset time (server runs UTC; show local)
RESET_FMT = "%a %-m/%-d %-I%p"    # e.g. "Wed 7/1 2PM" (GNU strftime; auto-falls back if unsupported)
# ============================================================================

RESET = "\033[0m"


def read_json_stdin():
    try:
        return json.load(sys.stdin)
    except:
        return {}

def format_k(n):
    """Format number in .1k units (e.g., 24.9k, 200k)"""
    n = max(0, n)
    k = n / 1000
    if k >= 100:
        return f"{k:.0f}k"  # No decimal for 100k+
    else:
        return f"{k:.1f}k"

def color(pct):
    if pct >= 90:
        return "\033[31m"  # red
    elif pct >= 70:
        return "\033[33m"  # yellow
    else:
        return "\033[32m"  # green

def get_git_branch(cwd_path):
    """Get current git branch if in a git repo"""
    try:
        result = subprocess.run(
            ['git', '-C', cwd_path, 'branch', '--show-current'],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            return f"\033[92m{branch}\033[0m" if branch else None
    except:
        pass
    return None

def used_total(usage):
    if not usage:
        return 0
    # Total input context = non-cached input + cached input (both read and created)
    # With prompt caching, input_tokens only shows NON-cached portion (often near 0)
    # cache_read_input_tokens = tokens served from cache
    # cache_creation_input_tokens = tokens being added to cache
    # Do NOT include output_tokens - those are generated, not context
    return (
        usage.get('input_tokens', 0) +
        usage.get('cache_read_input_tokens', 0) +
        usage.get('cache_creation_input_tokens', 0)
    )

def is_synthetic_model(j):
    model = j.get('message', {}).get('model', '').lower()
    return model == '<synthetic>' or 'synthetic' in model

def is_assistant_message(j):
    return j.get('message', {}).get('role') == 'assistant'

def is_sub_context(j):
    return j.get('isSidechain') == True

def has_no_response_content(j):
    content = j.get('message', {}).get('content', [])
    if isinstance(content, list):
        for item in content:
            if item and item.get('type') == 'text':
                text = str(item.get('text', ''))
                if 'no response requested' in text.lower():
                    return True
    return False

def parse_timestamp(j):
    ts = j.get('timestamp')
    if ts:
        try:
            from datetime import datetime
            return datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
        except:
            pass
    return float('-inf')

def newest_main_usage_by_timestamp(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    latest_ts = float('-inf')
    latest_usage = None

    try:
        with open(transcript_path, 'r') as f:
            lines = f.readlines()
    except:
        return None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue

        try:
            j = json.loads(line)
        except:
            continue

        usage = j.get('message', {}).get('usage')

        if (is_sub_context(j) or
            is_synthetic_model(j) or
            j.get('isApiErrorMessage') == True or
            used_total(usage) == 0 or
            has_no_response_content(j) or
            not is_assistant_message(j)):
            continue

        ts = parse_timestamp(j)
        if ts > latest_ts:
            latest_ts = ts
            latest_usage = usage
        elif ts == latest_ts and used_total(usage) > used_total(latest_usage):
            latest_usage = usage

    return latest_usage


# ----------------------------- ADD 1 helpers --------------------------------
def account_label():
    """Short label for the active Claude account, re-read from ~/.claude.json on every
    render so it tracks account switches. Returns None (widget hidden) on any problem.
    Reads ONLY the non-secret profile fields (displayName / emailAddress / organizationName)
    — never tokens, UUIDs, or anything else in the file."""
    if not SHOW_ACCOUNT:
        return None
    try:
        with open(os.path.expanduser("~/.claude.json")) as f:
            oa = (json.load(f) or {}).get("oauthAccount") or {}
    except Exception:
        return None

    email = (oa.get("emailAddress") or "").strip()
    local, _, domain = email.partition("@")
    domain_label = domain.split(".")[0] if domain else ""
    display = (oa.get("displayName") or "").strip()
    org = (oa.get("organizationName") or "").strip()

    mode = ACCOUNT_MODE
    if mode == "email_local":
        label = local or display
    elif mode == "email":
        label = email or display
    elif mode == "display_name":
        label = display or local
    elif mode == "org":
        label = org or domain_label or local
    elif mode == "smart":
        # ignore the auto-generated "<email>'s Organization" placeholder
        label = org if (org and "'s Organization" not in org) else (domain_label or local or display)
    else:  # "email_domain" (default) and any unknown value
        label = domain_label or local or display

    label = (label or "").strip()
    if not label:
        return None
    if len(label) > ACCOUNT_MAXLEN:
        label = label[:ACCOUNT_MAXLEN - 1] + "…"  # …
    return label


# ----------------------------- ADD 2 helpers --------------------------------
def _rate_pct(input_data, window):
    """used_percentage for a rate-limit window ('five_hour' | 'seven_day'), or None if
    absent. rate_limits appears only for Pro/Max after the first API response, and each
    window can be independently absent — so all access is defensive."""
    rl = input_data.get("rate_limits") or {}
    w = rl.get(window) or {}
    pct = w.get("used_percentage")
    if pct is None:
        return None
    try:
        return float(pct)
    except (TypeError, ValueError):
        return None

def _rate_reset(input_data, window):
    """Formatted reset time for a rate-limit window from rate_limits.<window>.resets_at
    (Unix epoch seconds), in RESET_TZ. None if absent/unparseable."""
    rl = input_data.get("rate_limits") or {}
    w = rl.get(window) or {}
    ts = w.get("resets_at")
    if not ts:
        return None
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromtimestamp(ts, ZoneInfo(RESET_TZ))
    except Exception:
        dt = datetime.fromtimestamp(ts)  # fallback: system local time
    try:
        return dt.strftime(RESET_FMT)
    except ValueError:
        return dt.strftime("%a %m/%d %I%p")  # padded fallback for non-GNU strftime

def rate_segments(input_data):
    """Colored 'wk NN%' / '5h NN%' segments for whichever windows are present+enabled."""
    out = []
    if SHOW_WEEKLY:
        p = _rate_pct(input_data, "seven_day")
        if p is not None:
            seg = f"{color(p)}wk {round(p)}%{RESET}"
            if SHOW_WEEKLY_RESET:
                r = _rate_reset(input_data, "seven_day")
                if r:
                    seg += f" \033[90m↻ {r}{RESET}"  # dim "↻ <reset time>"
            out.append(seg)
    if SHOW_FIVE_HOUR:
        p = _rate_pct(input_data, "five_hour")
        if p is not None:
            out.append(f"{color(p)}5h {round(p)}%{RESET}")
    if out and RATE_ICON:
        out[0] = f"{RATE_ICON} {out[0]}"
    return out


def main():
    input_data = read_json_stdin()

    # Get model info
    model = input_data.get('model', {})
    model_name = f"\033[95m{model.get('display_name', 'Claude')}\033[0m"
    model_id = model.get('id', '')
    if 'sonnet' in model_id.lower():
        model_icon = "🧠"
    elif 'opus' in model_id.lower():
        model_icon = "🚀"
    elif 'haiku' in model_id.lower():
        model_icon = "⚡"
    else:
        model_icon = "🤖"

    # ADD 1: active account (re-read each render)
    acct = account_label()
    acct_display = f"{ACCOUNT_ICON} {ACCOUNT_COLOR}{acct}{RESET}" if acct else ""

    # Get workspace info
    workspace = input_data.get('workspace', {})
    cwd_path = workspace.get('current_dir', os.getcwd())
    cwd = os.path.basename(cwd_path) if cwd_path else ''
    cwd_display = f"📁 \033[36m{cwd}\033[0m" if cwd else ""

    # Get git branch
    git_branch = get_git_branch(cwd_path) if cwd_path else None
    git_display = f"({git_branch})" if git_branch else ""

    # Get timestamp. Build the day separately so we avoid %-d (POSIX) / %#d (Windows).
    _now = datetime.now()
    now = f"{_now.strftime('%b')} {_now.day} {_now.strftime('%H:%M:%S')}"
    time_display = f"\033[90m{now}\033[0m"

    # ADD 2: rate-limit usage segments (line 2)
    rsegs = rate_segments(input_data)
    rate_tail = ("   " + "  ".join(rsegs)) if rsegs else ""

    transcript_path = input_data.get('transcript_path')

    # Get usage from transcript
    usage = newest_main_usage_by_timestamp(transcript_path)

    # Line 1 parts (shared by both states)
    parts = [
        f"{model_icon} {model_name}",
        acct_display,
        cwd_display,
        git_display,
        f"⏱️  {time_display}"
    ]
    status_line = " | ".join(p for p in parts if p)

    if not usage:
        # Initial status line before first response
        print(f"{status_line}")
        print(f"\033[36mcontext usage starts after first response\033[0m{rate_tail}")
        return

    # Calculate usage. The live context-window size comes from the payload
    # (context_window.context_window_size: 200000 default, 1000000 for 1M tiers),
    # so the % bar is correct on 1M sessions instead of dividing by a fixed 200k.
    # Fall back to the CONTEXT_WINDOW constant if the field is absent (older CC).
    window = (input_data.get("context_window") or {}).get("context_window_size") or CONTEXT_WINDOW
    used = used_total(usage)
    pct = round((used * 1000) / window) / 10 if window > 0 else 0

    # Usage display with progress bar (clamp the fill so a >100% reading can't overflow)
    bar_width = 20
    filled = max(0, min(bar_width, int((pct / 100) * bar_width)))
    bar = "█" * filled + "░" * (bar_width - filled)
    usage_display = f"{color(pct)}{pct:.1f}%\033[0m {bar} \033[33m{format_k(used)}/{format_k(window)}\033[0m"

    print(f"{status_line}")
    print(f"context: {usage_display}{rate_tail}")

if __name__ == "__main__":
    main()
