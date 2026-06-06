#!/usr/bin/env python3
"""Reocities CLI - manage your Reocities site from the terminal."""
import os
import sys
import json
import argparse
import fnmatch
import webbrowser
import configparser
from pathlib import Path

import requests

__version__ = "2.0.0"

# Use the canonical www host. reocities.xyz 301-redirects to www, and a 301 turns
# a POST upload into a GET, which the API rejects - so target www directly.
DEFAULT_BASE_URL = "https://www.reocities.xyz"
BULK_BATCH_SIZE = 10
IGNORE_FILES = (".gitignore", ".reocitiesignore")


class Config:
    """Reads and writes ~/.reocities/config."""

    def __init__(self):
        self.dir = Path.home() / ".reocities"
        self.file = self.dir / "config"

    def read(self):
        if not self.file.exists():
            return {}
        parser = configparser.ConfigParser()
        parser.read(self.file)
        if "default" not in parser:
            return {}
        return dict(parser["default"])

    def write(self, api_key, base_url=DEFAULT_BASE_URL):
        self.dir.mkdir(exist_ok=True)
        parser = configparser.ConfigParser()
        parser["default"] = {"api_key": api_key, "base_url": base_url}
        with open(self.file, "w") as fh:
            parser.write(fh)
        # Best effort on POSIX; chmod is a no-op worth skipping if it fails on Windows.
        try:
            os.chmod(self.file, 0o600)
        except OSError:
            pass

    def clear(self):
        if self.file.exists():
            self.file.unlink()
            return True
        return False


class Client:
    """Thin wrapper over the Reocities HTTP API."""

    def __init__(self, api_key, base_url=DEFAULT_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": api_key,
            "User-Agent": f"reocities-cli/{__version__}",
        })

    def _url(self, path):
        return f"{self.base_url}{path}"

    @staticmethod
    def _parse(response):
        if not response.content:
            return {"error": f"empty response (HTTP {response.status_code})"}
        try:
            data = response.json()
        except ValueError:
            return {"error": f"non-JSON response (HTTP {response.status_code})",
                    "raw": response.text[:500]}
        if response.status_code >= 400 and "error" not in data:
            data["error"] = f"HTTP {response.status_code}"
        return data

    def upload_one(self, file_path, folder=None, overwrite=True):
        with open(file_path, "rb") as fh:
            files = {"file": (Path(file_path).name, fh.read())}
        data = {"overwrite": "true" if overwrite else "false"}
        if folder:
            data["folder"] = folder
        return self._parse(self.session.post(self._url("/api/upload"), files=files, data=data))

    def upload_bulk(self, batch, folder=None, overwrite=True):
        # batch is a list of (local_path, remote_name). The server reads $_FILES['files']
        # as an array, so every part must use the same "files[]" field name - a list of
        # tuples does that; a dict would collapse them to one entry.
        if len(batch) > BULK_BATCH_SIZE:
            raise ValueError(f"max {BULK_BATCH_SIZE} files per bulk upload")
        parts = []
        for local_path, remote_name in batch:
            parts.append(("files[]", (remote_name, Path(local_path).read_bytes())))
        data = {"overwrite": "true" if overwrite else "false"}
        if folder:
            data["folder"] = folder
        return self._parse(self.session.post(self._url("/api/bulk-upload"), files=parts, data=data))

    def list_dir(self, path=None, recursive=False):
        params = {}
        if path:
            params["path"] = path
        if recursive:
            params["recursive"] = "true"
        return self._parse(self.session.get(self._url("/api/files"), params=params))

    def read_file(self, path):
        """Return raw bytes of a remote file, or None on failure."""
        params = {"action": "read", "path": path, "download": "1"}
        response = self.session.get(self._url("/api/files"), params=params)
        if response.status_code >= 400:
            return None
        return response.content

    def delete(self, path):
        return self._parse(self.session.delete(self._url("/api/files"),
                                               json={"path": path}))

    def make_folder(self, name, parent=None):
        data = {"name": name}
        if parent:
            data["parent"] = parent
        return self._parse(self.session.post(self._url("/api/folders"), data=data))


# --- helpers -------------------------------------------------------------

def load_ignore_patterns(directory):
    patterns = []
    for name in IGNORE_FILES:
        ignore_file = directory / name
        if not ignore_file.exists():
            continue
        for line in ignore_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def is_ignored(file_path, base_dir, patterns):
    rel = file_path.relative_to(base_dir).as_posix()
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(file_path.name, pattern):
            return True
    # Never ship the version-control directory.
    return ".git/" in rel + "/" or rel.startswith(".git")


def collect_files(directory):
    patterns = load_ignore_patterns(directory)
    found = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not is_ignored(path, directory, patterns):
            found.append((path, path.relative_to(directory).as_posix()))
    return found


def flatten_tree(entries, into=None):
    """Turn the server's nested directory listing into a flat list of file entries."""
    into = into if into is not None else []
    for entry in entries:
        if entry.get("type") == "directory":
            flatten_tree(entry.get("children", []), into)
        else:
            into.append(entry)
    return into


def human_size(size):
    if not isinstance(size, (int, float)):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    return 1


# --- commands ------------------------------------------------------------

def resolve_credentials(args):
    """Order of precedence: CLI flag, environment, saved config."""
    cfg = Config().read()
    api_key = args.api_key or os.environ.get("REOCITIES_API_KEY") or cfg.get("api_key")
    base_url = (args.base_url or os.environ.get("REOCITIES_BASE_URL")
                or cfg.get("base_url") or DEFAULT_BASE_URL)
    return api_key, base_url


def require_client(args):
    api_key, base_url = resolve_credentials(args)
    if not api_key:
        print("error: not logged in - run 'reocities login <api-key>' "
              "or set REOCITIES_API_KEY", file=sys.stderr)
        return None
    return Client(api_key, base_url)


def cmd_login(args):
    base_url = args.base_url or os.environ.get("REOCITIES_BASE_URL") or DEFAULT_BASE_URL
    client = Client(args.api_key, base_url)
    result = client.list_dir()
    if "error" in result:
        return fail(f"login failed: {result['error']}")
    Config().write(args.api_key, base_url)
    print(f"logged in to {base_url}")
    return 0


def cmd_logout(args):
    print("logged out" if Config().clear() else "not logged in")
    return 0


def cmd_push(args):
    client = require_client(args)
    if not client:
        return 1
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        return fail(f"not a directory: {args.directory}")

    files = collect_files(directory)
    if not files:
        print("nothing to upload")
        return 0

    print(f"{len(files)} file(s) from {directory}")
    if args.dry_run:
        for _, remote in files:
            print(f"  would upload {remote}")
        return 0

    # The bulk endpoint stores every file in one folder and keeps only the
    # basename, so group by parent directory to preserve the tree.
    groups = {}
    for local_path, remote in files:
        folder, _, name = remote.rpartition("/")
        groups.setdefault(folder, []).append((local_path, name))

    uploaded = failed = 0
    for folder in sorted(groups):
        items = groups[folder]
        for start in range(0, len(items), BULK_BATCH_SIZE):
            batch = items[start:start + BULK_BATCH_SIZE]
            result = client.upload_bulk(batch, folder=folder or None,
                                        overwrite=not args.no_overwrite)
            if "error" in result:
                print(f"  batch failed ({folder or '/'}): {result['error']}")
                failed += len(batch)
                continue
            for item in result.get("uploaded", []):
                print(f"  + {item.get('path', item.get('filename', '?'))}")
                uploaded += 1
            for item in result.get("failed", []):
                print(f"  ! {item.get('filename', '?')}: {item.get('error', 'failed')}")
                failed += 1
    print(f"done: {uploaded} uploaded, {failed} failed")
    return 1 if failed else 0


def cmd_upload(args):
    client = require_client(args)
    if not client:
        return 1
    failed = 0
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"  ! {name}: not a file")
            failed += 1
            continue
        result = client.upload_one(path, args.folder, overwrite=not args.no_overwrite)
        if result.get("success"):
            print(f"  + {result.get('path', path.name)}")
        else:
            print(f"  ! {path.name}: {result.get('error', result.get('message', 'failed'))}")
            failed += 1
    return 1 if failed else 0


def cmd_list(args):
    client = require_client(args)
    if not client:
        return 1
    result = client.list_dir(args.folder, recursive=args.recursive)
    if "error" in result:
        return fail(result["error"])
    entries = result.get("files", [])
    if args.recursive:
        entries = flatten_tree(entries)
    if not entries:
        print("(empty)")
        return 0
    for entry in entries:
        if entry.get("type") == "directory":
            print(f"  {entry['path']}/")
        else:
            print(f"  {entry.get('path', entry.get('name'))}  ({human_size(entry.get('size'))})")
    return 0


def cmd_cat(args):
    client = require_client(args)
    if not client:
        return 1
    content = client.read_file(args.path)
    if content is None:
        return fail(f"could not read {args.path}")
    sys.stdout.buffer.write(content)
    return 0


def cmd_pull(args):
    client = require_client(args)
    if not client:
        return 1
    dest = Path(args.directory).resolve()
    result = client.list_dir(args.folder, recursive=True)
    if "error" in result:
        return fail(result["error"])
    files = flatten_tree(result.get("files", []))
    if not files:
        print("nothing to download")
        return 0
    saved = failed = 0
    for entry in files:
        remote = entry.get("path") or entry.get("name")
        content = client.read_file(remote)
        if content is None:
            print(f"  ! {remote}: download failed")
            failed += 1
            continue
        local = dest / remote
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(content)
        print(f"  + {remote}")
        saved += 1
    print(f"done: {saved} downloaded, {failed} failed -> {dest}")
    return 1 if failed else 0


def cmd_delete(args):
    client = require_client(args)
    if not client:
        return 1
    failed = 0
    for path in args.paths:
        result = client.delete(path)
        if result.get("success"):
            print(f"  - {path}")
        else:
            print(f"  ! {path}: {result.get('error', result.get('message', 'failed'))}")
            failed += 1
    return 1 if failed else 0


def cmd_mkdir(args):
    client = require_client(args)
    if not client:
        return 1
    result = client.make_folder(args.name, args.parent)
    if result.get("success"):
        print(f"created {args.parent + '/' if args.parent else ''}{args.name}")
        return 0
    return fail(result.get("error", result.get("message", "failed")))


def cmd_whoami(args):
    client = require_client(args)
    if not client:
        return 1
    result = client.list_dir(recursive=True)
    if "error" in result:
        return fail(result["error"])
    files = flatten_tree(result.get("files", []))
    total = sum(f.get("size") or 0 for f in files)
    print(f"server:  {client.base_url}")
    print(f"files:   {len(files)}")
    print(f"storage: {human_size(total)}")
    return 0


def cmd_open(args):
    _, base_url = resolve_credentials(args)
    webbrowser.open(base_url)
    print(f"opening {base_url}")
    return 0


def cmd_version(args):
    print(f"reocities-cli {__version__}")
    return 0


BANNER = r"""
 ____                _ _   _
|  _ \ ___  ___   ___(_) |_(_) ___  ___
| |_) / _ \/ _ \ / __| | __| |/ _ \/ __|
|  _ <  __/ (_) | (__| | |_| |  __/\__ \
|_| \_\___|\___/ \___|_|\__|_|\___||___/

Manage your Reocities site from the command line.
"""


def build_parser():
    parser = argparse.ArgumentParser(prog="reocities", description="Reocities CLI")
    parser.add_argument("--api-key", help="API key (overrides config and env)")
    parser.add_argument("--base-url", help="API base URL (for self-hosted instances)")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("login", help="save an API key")
    p.add_argument("api_key")
    p.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="remove the saved API key").set_defaults(func=cmd_logout)

    p = sub.add_parser("push", help="upload a whole directory")
    p.add_argument("directory", nargs="?", default=".")
    p.add_argument("--dry-run", action="store_true", help="list what would upload, send nothing")
    p.add_argument("--no-overwrite", action="store_true", help="skip files that already exist")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("upload", help="upload one or more files")
    p.add_argument("files", nargs="+")
    p.add_argument("--folder", help="target folder on the site")
    p.add_argument("--no-overwrite", action="store_true")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("list", help="list files on the site")
    p.add_argument("--folder", help="folder to list (default: root)")
    p.add_argument("--recursive", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("cat", help="print a remote file to stdout")
    p.add_argument("path")
    p.set_defaults(func=cmd_cat)

    p = sub.add_parser("pull", help="download the site to a local directory")
    p.add_argument("directory", nargs="?", default=".")
    p.add_argument("--folder", help="only download this folder")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("delete", help="delete files or folders")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("mkdir", help="create a folder")
    p.add_argument("name")
    p.add_argument("--parent", help="parent folder")
    p.set_defaults(func=cmd_mkdir)

    sub.add_parser("whoami", help="show the active site and storage use").set_defaults(func=cmd_whoami)
    sub.add_parser("open", help="open the site in a browser").set_defaults(func=cmd_open)
    sub.add_parser("version", help="show the version").set_defaults(func=cmd_version)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        print(BANNER)
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except requests.RequestException as exc:
        return fail(f"network error: {exc}")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
