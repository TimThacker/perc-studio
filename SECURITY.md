# Security Policy

Please do not report security vulnerabilities in public issues.

Use GitHub's private reporting instead:
https://github.com/TimThacker/perc-studio/security/advisories/new

You can expect an initial response within 7 days.

The PERC Studio app makes no network calls and stores only local settings (in `%LOCALAPPDATA%` and `%APPDATA%`).
Some HTML reports written by the `perc-studio` automation CLI load plotly.js from its CDN when opened in a
browser.
