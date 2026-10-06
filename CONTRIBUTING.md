# Contributing

Thanks for helping! Bug reports, ideas and pull requests are all welcome.

## Reporting a bug

Open an issue with: the release version (or commit), what you did, what you expected and what happened. Attach
`%LOCALAPPDATA%\DeadAsDiscoAP\last-run.log` and, for in-game problems, the session's `core\UE4SS.log`. **Never attach save files.**

## Getting started

```
git clone <this repository>
cd <folder>
python tools/setup-dev.py
.venv\Scripts\python.exe tools/ap-slice-dev.py Tests
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the layout, all commands and how the pieces fit together.

## Pull requests

- Keep a PR focused on one change. Describe what it does and how you tested it.
- Run before pushing: the Python tests, `tools/run-lua-tests.py` and `node tools/test-ap-catalog.mjs`. If you touch options, run
  `tools/make-template.py` and commit the regenerated YAML.
- Files use LF line endings (enforced by `.gitattributes`); the release certificate pins file hashes of the Lua mod and the client.
- Add or update a test for behaviour you change. The Lua mod has offline fixtures in `tools/test-ap-*.lua`.
- Anything that touches the in-game mod or the save handling needs a real play test; say in the PR what you tried. Test only on a
  dedicated Archipelago profile, never on your own save, with Steam Cloud off.
- Do not commit save files, game files, downloaded binaries (the UE4SS archive is downloaded by `setup-dev.py`) or credentials.
- Mechanisms that are not yet verified in live play stay behind the protected test mode (`archipelago/dadap/capabilities.py`) until
  someone confirms them and records how.

## Code style

Match the surrounding code. Python is plain standard-library style, Lua follows the existing module layout in `archipelago/game-mod/`.
