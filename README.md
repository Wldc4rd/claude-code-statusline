# claude-code-statusline

A two-line status line for [Claude Code](https://docs.claude.com/en/docs/claude-code/statusline) that shows the current model, working directory, git branch, date + time, and accurate context-window usage with a progress bar.

![Example output](docs/example.png)

## What it shows

**Line 1** — model · `📁 cwd` · `(branch)` · `⏱️  May 7 09:05:14`

**Line 2** — `context: 18.9% ███░░░░░░░░░░░░░░░░░ 37.7k/200k`

Context usage is computed from the transcript by summing `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` on the most recent main-thread assistant turn (sub-context, synthetic, error, and "no response requested" turns are excluded). The percentage is colored green / yellow / red at 70 % and 90 % thresholds.

## Install

The script is a single file with **zero pip dependencies**. It uses [`uv`](https://docs.astral.sh/uv/) as the runner so the same source works on macOS, Linux, and Windows — and so users without a system Python can run it after a single `uv` install.

### 1. Install `uv`

**macOS / Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Or use a package manager you already have: `brew install uv`, `winget install --id=astral-sh.uv`, `scoop install uv`, `pipx install uv`.

### 2. Get the script

```bash
git clone https://github.com/Servosity/claude-code-statusline.git
```

### 3. Wire it into Claude Code

Edit `~/.claude/settings.json` (or `%USERPROFILE%\.claude\settings.json` on Windows) and add:

**macOS / Linux** — the script's shebang (`#!/usr/bin/env -S uv run --script`) makes it directly executable, so point Claude Code straight at the file:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/absolute/path/to/claude-code-statusline/statusline.py"
  }
}
```

If you'd rather keep `~/.claude/statusline.py` as the canonical path so updates are just `git pull`, symlink it:

```bash
ln -sf "$PWD/claude-code-statusline/statusline.py" ~/.claude/statusline.py
chmod +x ~/.claude/statusline.py   # already executable in the repo, harmless to repeat
```

**Windows** — shebangs aren't executable on Windows, so invoke `uv` explicitly:

```json
{
  "statusLine": {
    "type": "command",
    "command": "uv run \"C:\\path\\to\\claude-code-statusline\\statusline.py\""
  }
}
```

(Use forward slashes or escape the backslashes — both work.)

### 4. Restart Claude Code

The status line refreshes on every render after that. The first run downloads a managed Python interpreter via `uv` if you don't have one — subsequent runs are instant.

## Configuration

Open `statusline.py` and edit the constants near the top:

| Constant | Default | What it controls |
| --- | --- | --- |
| `CONTEXT_WINDOW` | `200_000` | Total context budget used to compute the percentage. Bump to `1_000_000` for the 1M-context Opus tier. |

The model icon is selected from the model id: 🚀 Opus, 🧠 Sonnet, ⚡ Haiku, 🤖 anything else.

The date format is built from `datetime.now()`:

```python
_now = datetime.now()
now = f"{_now.strftime('%b')} {_now.day} {_now.strftime('%H:%M:%S')}"
```

This avoids the `%-d` / `%#d` strftime split between POSIX and Windows. Swap it for `_now.strftime("%Y-%m-%d %H:%M:%S")` for ISO format, or drop the date entirely for time only.

## Requirements

- [`uv`](https://docs.astral.sh/uv/) — handles the Python interpreter for you
- A terminal that renders ANSI 256-color escape sequences (every modern terminal does, including Windows Terminal)
- `git` on `PATH` if you want the branch segment

The PEP 723 inline metadata in the script (`# /// script` block) declares `requires-python = ">=3.9"`. `uv` reads this header on each run and provides a matching interpreter automatically.

## License

MIT — see [LICENSE](LICENSE).
