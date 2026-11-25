"""Shared round bindings and result handling for Atlas landing commands."""

from contextlib import contextmanager
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import mkdtemp
from uuid import uuid4


class Incomplete(ValueError):
    """A stage could not establish its result."""

    def __init__(self, message, **evidence):
        super().__init__(message)
        self.evidence = evidence


def require(condition, message):
    if not condition:
        raise Incomplete(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def fingerprint(value):
    return sha256(canonical(value)).hexdigest()


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def unique(pairs):
    value = dict(pairs)
    require(len(value) == len(pairs), "Duplicate JSON field")
    return value


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique)


def save(path, value):
    raw = canonical(value) + b"\n"
    temp = path.with_name(f".{uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "nt":
            os.rename(temp, path)
        else:
            os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"path": str(path), "sha256": sha256(raw).hexdigest()}


@contextmanager
def round_lock(path):
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise Incomplete("Another command owns this round") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Incomplete("Another command owns this round") from exc
        yield


class Round:
    def __init__(self, settings):
        self.settings = settings.resolve(strict=True)
        self.config = decode(self.settings.read_bytes())
        self.output = self.path(self.config["output"])
        require(self.output != self.settings.parent and self.output not in self.settings.parents,
                "Round output must be a separate scratch directory")
        self.output.mkdir(parents=True, exist_ok=True)

    def path(self, value):
        return (self.settings.parent / value).resolve()

    def checked(self, reference):
        path = self.path(reference["path"])
        require(digest(path) == reference["sha256"], f"Fingerprint differs for {path}")
        return path

    def json(self, reference):
        path = self.path(reference["path"])
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == reference["sha256"], f"Fingerprint differs for {path}")
        return decode(raw)

    def local(self, name, scope):
        return self.output / f"{name}-{fingerprint(scope)}.json"

    def stage(self, name):
        return Path(mkdtemp(prefix=f"{name}-", dir=self.output))

    def launch(self, label, argv, work, logs, *, cwd=None, env=None, allowed=(0,)):
        start = time.monotonic()
        command = [str(arg) for arg in argv]
        stdout = logs / f"{label}.stdout"
        stderr = logs / f"{label}.stderr"
        print(json.dumps({"stage": label, "command": command, "progress": str(stdout)}), file=sys.stderr, flush=True)
        with stdout.open("xb") as out, stderr.open("xb") as err:
            result = subprocess.run(command, cwd=cwd or work, env=env, stdout=out, stderr=err, check=False)
        evidence = {
            "stage": label, "child_exit": result.returncode, "stdout": str(stdout), "stderr": str(stderr),
            "elapsed_seconds": time.monotonic() - start, "command": command,
        }
        if result.returncode not in allowed:
            raise Incomplete(f"{label} exited {result.returncode}", **evidence)
        return evidence


def run(operation, settings):
    round_ = None
    started = time.monotonic()
    try:
        round_ = Round(settings)
        with round_lock(round_.output / "round.lock"):
            if operation == "capture-compare":
                from atlas_land_compare import compare
                result = compare(round_)
            else:
                from atlas_land_prepare import prepare
                result = prepare(round_)
    except (OSError, ValueError, KeyError, TypeError, IndexError, ImportError) as exc:
        result = {"status": "INCOMPLETE", "exit": 2, "reason": str(exc), **getattr(exc, "evidence", {})}
        if round_ is not None:
            try:
                result["failure_record"] = save(round_.output / f"failure-{uuid4().hex}.json", result)
            except OSError as report_error:
                result["failure_record_error"] = str(report_error)
    print(json.dumps({**result, "command_seconds": time.monotonic() - started}, allow_nan=False))
    return result["exit"]
