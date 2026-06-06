# Changelog

## 2.0.0

### Fixed
- Uploads failed against the default host. `reocities.xyz` redirects to `www`,
  and the redirect turned the upload POST into a GET that the API rejected. The
  default base URL is now `www.reocities.xyz`.
- `push` only uploaded one file per batch of ten because of a bug in how the
  multipart request was built. All files are sent now.
- `push` flattened subdirectories into the site root; it now preserves the tree.
- `list --folder` listed the root instead of the requested folder, and
  `--recursive` had no effect.

### Added
- `pull` — download your site to a local directory.
- `cat` — print a remote file to stdout.
- `mkdir` — create a folder.
- `whoami` — show the active site and storage use.
- `open` — open your site in a browser.
- `push --dry-run` and `--no-overwrite`.
- `--base-url` for self-hosted instances.
- `REOCITIES_API_KEY` and `REOCITIES_BASE_URL` environment variables.
- `.reocitiesignore` support alongside `.gitignore`.
- An MIT `LICENSE` file.
