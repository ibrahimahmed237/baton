"""Supervise a runner and all of its subprocesses until they are reaped."""
import multiprocessing
import os
import signal


def _run(connection, runner, prompt, folder):
    os.setsid()
    connection.send(('ready', None))
    try:
        connection.send((runner.ask(prompt, folder, read_only=True), None))
    except Exception as error:
        connection.send((None, error))
    finally:
        connection.close()


class RunnerProcess:
    """Isolate even runners without cancellation handles in a process group."""
    def __init__(self, runner, prompt, folder):
        context = multiprocessing.get_context('fork')
        self.connection, child = context.Pipe(duplex=False)
        self.process = context.Process(target=_run, args=(child, runner, prompt, folder))
        self.process.start()
        child.close()

    def poll(self, seconds):
        """Return a completed answer/error pair or None while still running."""
        if self.connection.poll(seconds):
            try:
                value = self.connection.recv()
                return None if value == ('ready', None) else value
            except EOFError:
                return None, RuntimeError('runner_process_exited')
        return None

    def _signal(self, group_signal, direct):
        try:
            os.killpg(self.process.pid, group_signal)
        except OSError:
            if self.process.is_alive():
                try:
                    direct()
                except OSError:
                    pass

    def close(self):
        """Try group and direct termination; always join and dispose of the pipe."""
        try:
            try:
                self._signal(signal.SIGTERM, self.process.terminate)
            finally:
                self.process.join(.1)
        finally:
            try:
                try:
                    self._signal(signal.SIGKILL, self.process.kill)
                finally:
                    self.process.join()
            finally:
                self.connection.close()
