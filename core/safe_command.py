"""A guard for commands the model wrote itself.

WHY THIS EXISTS
    `actions/dev_agent.py` asks a model to plan a project, and the plan contains
    `"run_command": "python main.py"`. That string is then handed to
    `subprocess.run()` and executed. The model wrote it. Nothing checked it.

    This is not a hypothetical. It is the difference between two very different
    things that look identical in the code:

        "python main.py"        the feature working
        "rm -rf ~"              the model having a bad turn, or having read it
                                somewhere it should not have

    `subprocess.run(parts)` without `shell=True` already blocks shell
    metacharacters — `;`, `|`, `&&` are passed as literal arguments rather than
    interpreted — so the blast radius is one process, not a shell script. What
    it does *not* block is which process. `["rm", "-rf", "/"]` is a perfectly
    valid argv.

WHAT THIS CAN AND CANNOT DO
    It cannot make running a generated project safe: executing model-written code
    *is* the feature. What it can do is stop the command from reaching outside
    the project — deleting, escalating, or pulling something down — and it can
    say why, so the planner gets a reason instead of silence.

    Two rules, and they are different rules:

      the launcher must be one we recognise  — a build step launches a runtime
      nothing destructive may appear at all  — wherever it appears in the argv

    Everything it rejects is logged with the reason, because a guard that
    silently rewrites a command is worse than no guard: the project would run
    something other than what was planned and nobody would know.
"""
from __future__ import annotations

import re

# What a build/run step may launch. Deliberately small: these are runtimes a
# generated project actually uses, and adding one is a decision rather than a
# default. `bash`/`sh`/`cmd`/`powershell` are NOT here — a project that needs a
# shell script to start is a project that should say so in its plan, and letting
# the model pick a shell is how `["bash", "-c", ...]` gets in.
LAUNCHERS = {
    "python", "python3", "py", "pythonw",
    "node", "npm", "npx", "yarn", "pnpm", "bun", "deno", "tsc", "vite", "next", "expo",
    "go", "cargo", "rustc", "dotnet", "java", "javac", "mvn", "mvnw", "gradle", "gradlew",
    "ruby", "php", "perl", "lua", "rscript",
    # Python project runners, which are what a planner reaches for once a
    # project grows past a single script. Leaving these out would refuse
    # `streamlit run app.py` — a legitimate plan — which is the failure mode
    # that makes a guard get deleted instead of fixed.
    "streamlit", "flask", "uvicorn", "gunicorn", "fastapi", "django-admin",
    "poetry", "pipenv", "uv", "hatch", "pytest", "ruff", "mypy", "jupyter",
}

# Extensions stripped before matching, so `npm.cmd` on Windows is still `npm`.
_LAUNCH_EXTS = (".exe", ".cmd", ".bat")

# Refused anywhere in the argv, not just first. A destructive binary is
# destructive whether the model put it first or after a `--` it invented.
FORBIDDEN = {
    # deleting and overwriting
    "rm", "rmdir", "del", "erase", "format", "mkfs", "diskpart", "fdisk",
    "shred", "srm", "truncate", "dd",
    # privilege and system control
    "sudo", "su", "runas", "doas", "shutdown", "reboot", "halt", "poweroff",
    "taskkill", "pkill", "killall", "reg", "regedit", "sc", "net", "netsh",
    "systemctl", "launchctl", "chmod", "chown", "chattr", "attrib", "icacls",
    "takeown", "cacls",
    # pulling things off the network
    "curl", "wget", "nc", "ncat", "telnet", "ftp", "sftp", "scp", "rsync",
    "ssh", "bitsadmin", "certutil",
}

# Shell syntax. `shell=True` is not used, so these would arrive as literal
# arguments and simply break the command — but refusing them outright is the
# clearer failure, and it catches the case where a future edit adds shell=True.
_SHELL_CHARS = re.compile(r"[;&|`$><\n\r]")

MAX_ARGV = 24
MAX_TOKEN = 200

# A dependency name: letters, digits, dot, dash, underscore, an optional
# [extra], an optional version specifier. Anything else is not a package name.
_PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,-]+\])?"
                  r"([=<>!~]=?[A-Za-z0-9._*+!-]+)*$")


def _basename(token: str) -> str:
    """`C:\\Python\\python.exe` -> `python`, `npm.cmd` -> `npm`."""
    name = token.lower().replace("\\", "/").rsplit("/", 1)[-1]
    for ext in _LAUNCH_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def check(command: str) -> tuple[bool, str]:
    """(ok, reason). `reason` is '' when ok, else what is wrong with it.

    The reason is written to be handed back to the model, so it says what to do
    differently rather than only what was refused.
    """
    raw = (command or "").strip()
    if not raw:
        return False, "the plan did not include a run command"

    if _SHELL_CHARS.search(raw):
        return False, ("the run command contains shell syntax (one of ; & | ` $ > <). "
                       "It must be a single plain command — an interpreter and a path.")

    parts = raw.split()
    if len(parts) > MAX_ARGV:
        return False, f"the run command has {len(parts)} arguments; that is not a run command"
    if any(len(p) > MAX_TOKEN for p in parts):
        return False, "the run command contains an implausibly long argument"

    launcher = _basename(parts[0])
    if launcher not in LAUNCHERS:
        return False, (f"'{parts[0]}' is not a runtime I will launch a project with. "
                       f"Use one of: python, node, npm, go, cargo, dotnet, java.")

    for token in parts[1:]:
        if _basename(token) in FORBIDDEN:
            return False, (f"the run command tries to use '{token}', which is refused "
                           f"wherever it appears. A project's run command launches the "
                           f"project; it does not delete, escalate or download.")

    return True, ""


def safe_package(dep: str) -> str | None:
    """The installable name in `dep`, or None if it is not one.

    Dependencies come from the same model-written plan as the run command, and
    they are handed to `pip install` as arguments. `--index-url=…` is a
    perfectly valid argv entry and would be obeyed, which is why anything
    starting with a dash is refused rather than passed through.
    """
    name = (dep or "").strip()
    if not name or name.startswith("-"):
        return None
    if not _PKG.match(name):
        return None
    return name
