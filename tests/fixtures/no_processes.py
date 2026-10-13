"""A guard for tests: while it is active, nothing may start a process, replace the process or signal one."""
from __future__ import annotations

import os
import subprocess
from contextlib import ExitStack, contextmanager
from typing import Iterator
from unittest.mock import patch

_SUBPROCESS = ("run", "Popen", "call", "check_call", "check_output")
_OS = ("system", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
       "posix_spawn", "posix_spawnp", "kill", "killpg", "fork", "forkpty")


def _forbidden(name: str):
    def refuse(*args, **kwargs):
        raise AssertionError("a test root reached the real machine: %s%r" % (name, args[:1]))
    return refuse


@contextmanager
def no_processes() -> Iterator[None]:
    """Make every way of starting, replacing or signalling a process raise AssertionError."""
    with ExitStack() as stack:
        for name in _SUBPROCESS:
            stack.enter_context(patch.object(subprocess, name, _forbidden("subprocess." + name)))
        for name in _OS:
            if hasattr(os, name):
                stack.enter_context(patch.object(os, name, _forbidden("os." + name)))
        yield
