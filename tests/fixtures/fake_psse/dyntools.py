"""Stand-in for PSS/E's dyntools: returns the trace the fake psspy holds in memory (same process)."""

import psspy


class CHNF:
    def __init__(self, path):
        if psspy._S.get("monitored") == 0:  # real PSS/E then writes a header with no records, and dyntools fails
            raise ValueError("channel file has no data: zero channels were being monitored")
        self._trace = list(psspy._S["trace"])

    def get_data(self):
        names = {1: "V", 2: "F", 3: "P", 4: "Q"}
        data = {"time": [r[0] for r in self._trace]}
        for i in names:
            data[i] = [r[i] for r in self._trace]
        return ("fake", ""), dict(names, time="Time(s)"), data
