"""Optional diagnostic log owned by the chain parent."""
import json
from pathlib import Path


class RunLog:
    def __init__(self, stream):
        self._stream = stream

    def __bool__(self):
        return self._stream is not None

    def event(self, level, event, *, utc, step=None, detail=None):
        if self._stream is None:
            return
        row = {"utc": utc, "level": level, "event": event}
        if step is not None:
            row["step"] = step
        if detail is not None:
            row["detail"] = detail
        try:
            line = json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"
            self._stream.write(line)
            self._stream.flush()
        except (OSError, TypeError, ValueError):
            self.close()

    def close(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def open_run_log(journal_directory):
    try:
        stream = (Path(journal_directory) / "run.log").open("x", encoding="utf-8", newline="\n")
    except OSError:
        stream = None
    return RunLog(stream)
