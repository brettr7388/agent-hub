# Contributing

Agent Hub supports macOS and Linux and uses Python's standard library plus plain JavaScript and CSS. Windows is not supported yet.

Run the Python suite and each standalone JavaScript smoke script locally:

```sh
python3 -m unittest discover -s tests
for f in tests/*.js; do node "$f" || exit; done
```

Use fake CLI programs and temporary directories for tests. Do not include real credentials, private chat data, or provider tokens in fixtures or bug reports. For bugs, open a GitHub issue with your operating system, Python version, steps to reproduce, and relevant redacted logs. For security issues, use the private reporting instructions in [SECURITY.md](SECURITY.md).

Keep changes focused, explain user-visible behavior, and include tests when changing behavior. Pull requests should state which checks were run and any platform-specific limitations.
