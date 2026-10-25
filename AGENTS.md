# ACT WBEX Updater

- This is an independent Windows updater, not an ACT plugin or a WBEX compiler.
- Product metadata belongs to Intelligent Efficiency Team. Keep version metadata,
  pyproject.toml, changelog and release tag consistent.
- Runtime dependencies must remain standard-library only; do not import another
  project or compile/run plugin scripts during inspection or update.
- Preserve backups/rollback, GUID isolation, path validation and v241-first defaults.
- Keep theme changes responsive, interruptible and compatible with reduced motion.
- After runtime changes run `python -m unittest discover -s tests -p 'test_*.py'`.
- Build both layouts, verify EXE metadata and run each EXE's `--self-check` before release.
- Keep generated executables, credentials, personal paths and plugin packages out of Git.
