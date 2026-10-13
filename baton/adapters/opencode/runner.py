"""OpenCode background runs require an explicitly injected working binary."""
import json
from pathlib import Path
import subprocess

from ...domain.errors import NotAvailable
from ...ports.tool import SetupFinding


class OpenCodeRunner:
    """Probe an injected command; never use the damaged system CLI by default."""

    def __init__(self, command=None, binary=None, root=None):
        self.machine_environment = False
        self.command = command
        self.binary = binary
        self.root = Path(root).absolute() if root is not None else None

    def available(self):
        """Report reinstall when the injected binary is absent or cannot launch."""
        ok = False
        if self.command is not None and self.binary:
            try:
                ok = self.command([self.binary, "--version"], capture_output=True, text=True, timeout=5).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        return SetupFinding("runner", ok, "" if ok else "setup.runner_reinstall",
                            {"tool": "opencode", "reason": "reinstall", "fix_id": "reinstall"})

    def ask(self, prompt, folder, read_only=True):
        """Use a fresh CLI run with all mutating tools denied by permission settings."""
        if not read_only or not self.available().ok:
            raise NotAvailable()
        # The working-binary path is explicitly supplied. No local server access,
        # session resumption or attempt to obtain its generated password occurs.
        permission = {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow"}
        if self.root is None and not self.machine_environment:
            raise NotAvailable()
        import os
        environment = {**os.environ, "OPENCODE_CONFIG_CONTENT": json.dumps({"permission": permission})}
        if not self.machine_environment:
            environment.update({"XDG_DATA_HOME": str(self.root / ".local/share"),
                                "XDG_CONFIG_HOME": str(self.root / ".config"),
                                "XDG_CACHE_HOME": str(self.root / ".cache"),
                                "XDG_STATE_HOME": str(self.root / ".local/state")})
        try:
            result = self.command([self.binary, "run", "--format", "json", "--", prompt], cwd=folder,
                                  env=environment,
                                  capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            raise NotAvailable() from None
        if result.returncode != 0:
            raise NotAvailable()
        try:
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            return "\n".join(e.get("part", {}).get("text", "") for e in events if e.get("type") == "text")
        except (ValueError, AttributeError):
            raise NotAvailable() from None
