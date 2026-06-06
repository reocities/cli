# Reocities CLI

Manage your [Reocities](https://reocities.xyz) site from the command line — push a
whole folder, upload or delete single files, pull your site back down, and more.

## Install

```bash
pip install reocities-cli
```

This installs a `reocities` command. Works on Linux, macOS, and Windows
(Python 3.6+).

## Getting started

Grab an API key from your site's configuration page, then:

```bash
reocities login YOUR_API_KEY
reocities push ./my-site
```

Instead of `login` you can pass credentials per-command or via the environment:

```bash
export REOCITIES_API_KEY=...
reocities --api-key YOUR_API_KEY list
```

## Commands

| Command | What it does |
|---------|--------------|
| `login <api-key>` | Save your API key to `~/.reocities/config` |
| `logout` | Forget the saved key |
| `push [dir]` | Upload a whole directory (honors `.gitignore` / `.reocitiesignore`) |
| `upload <files...> [--folder F]` | Upload individual files |
| `pull [dir] [--folder F]` | Download your site to a local folder |
| `list [--folder F] [--recursive]` | List files on your site |
| `cat <path>` | Print a remote file to stdout |
| `mkdir <name> [--parent P]` | Create a folder |
| `delete <paths...>` | Delete files or folders |
| `whoami` | Show the active site and storage use |
| `open` | Open your site in a browser |
| `version` | Print the version |

### Useful flags

- `push --dry-run` — show what would upload without sending anything.
- `push --no-overwrite` / `upload --no-overwrite` — skip files that already exist.
- `--base-url https://example.com` — point at a self-hosted instance.

## Ignoring files

`push` skips anything matched by `.gitignore` or `.reocitiesignore` in the
directory you're uploading, and always skips `.git/`.

## License

MIT
