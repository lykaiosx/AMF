# AMF 4.14

**[Download the Windows installer](https://github.com/lykaiosx/AMF/releases/tag/v4.14)**

Run **AMF-4.14-Setup.exe**. It includes Python, Qt/PySide6 and all required Python
libraries. Installation runs offline without system Python or administrator access.
Close AMF before upgrading. Search and downloading still require internet access.

The local delivery folder contains the same installer named **Setup.exe**.
You can copy that EXE alone to another computer. GitHub's Code / Download ZIP
contains developer source, not the compiled installer.

Supported: x64 Windows 10 version 1809+ and Windows 11. ARM Windows requires x64
emulation and has not been tested. Older and 32-bit Windows are unsupported.
The installer is not code-signed.

## Changes

- Read EZTV or Anna's Archive once after completing site verification. Later searches reuse
  that browser session in the background. Cookies are saved locally; idle pages release
  rendering resources after one minute. A site can still require verification again when
  its session expires. Disabled sources are not searched.

- YTS sends verified torrent files, including metadata, instead of trackerless magnets. Older saved YTS magnets use the same path; failed fetches stay in the cart for retry.

- Proportional square-canvas app icons and matching setup, shortcut and uninstall artwork.

- Readable version badge and transparent label backgrounds in all themes, including after resizing.
- Supplied white/black brand logos follow the theme. Tabs end with History, then Settings.
- Compact, vertically centered appearance controls and aligned download-directory fields.
- Source filters and visible results follow enabled sources immediately, including duplicate groups.
- YTS uses its working movie API, preserving resolution, size and peer counts. Each search reads
  up to 50 matching movies and reports how many were loaded versus the provider total.

Previous features:

- Update checks at startup (can be disabled in Settings), release notes, cancellable
  downloads, SHA-256 verification and an explicit Install Update action.
- Magnet info-hash duplicate grouping, including equivalent hexadecimal/base32
  hashes. Source names appear together and source filters still work. Rows without
  a known info hash are matched only by their exact link, never just their title.
- Searchable, paged History tab with client, time, destination and send outcome.
  History begins with this version. Previously sent items prompt before resending.
- Source Health / Retry explains connection, authentication and browser checks.
- Save, load and delete search presets, including filters and enabled sources.
- Existing password fields migrate into Windows Credential Manager when AMF opens.
  Credentials belong to the current Windows account; re-enter them after moving
  configuration to a different account or device. Old external backups are not altered.
- Interrupted-session notice, last-good cart backup, explicit backup restoration,
  and diagnostic export using a strict allowlist. Reports exclude credentials,
  titles, URLs, local paths and raw log contents.

Existing features remain available:

- Screen-aware window sizing, compact controls on smaller windows, wrapping
  action bars and scrollable pages.
- Virtual cart table without a dropdown and table objects for every torrent.
  Double-click Destination to change it.
- Background client transfers with cancellation between requests. Durable
  receipts record confirmed sends; failed and unprocessed entries remain.
- Title resolution queues at most eight requests. Closing with active workers
  is deferred to avoid destroying a running thread.
- Existing providers, Test All, selection controls, clients and routing remain:
  Games, Movies, Series, Anime/Movies, Anime/Series, Music and Books.

## Installation and data

AMF installs in `%LOCALAPPDATA%\Programs\AMF`. Start-menu and optional desktop
shortcuts launch its private runtime directly. Existing `config.json`, `cart.json`
and backups survive upgrades and uninstallation. Setup verifies the version and
application window. Logs are `install-check.log` and `startup-error.log` in the
installation folder.

Tested on the development Windows PC with an isolated runtime: 20,000 cart rows,
1,000 simulated client transfers including failures and cancellation, and four
tabs at three window sizes. This is not testing on every supported Windows release
or a guarantee against every possible crash.

## Build from source

Install the official [Inno Setup compiler](https://jrsoftware.org/isdl.php), then run:

```powershell
.\build.ps1 -Compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

Building needs internet to prepare the pinned runtime. Output is
`dist\AMF-4.14-Setup.exe` and `Setup.exe`. Runtime and installer binaries are excluded
from Git; use GitHub Releases for the ready-to-install EXE.

`runtime_setup.ps1` checks the official Python archive and bundled PyPA pip zipapp
with SHA-256. Pip and runtime libraries include their upstream license notices.
Run `tests\test_scalability.py` with the prepared runtime to test rendering, edits,
simulated transfers, cancellation, receipt recovery and UI responsiveness.
Run `tests\test_productivity.py` for credential migration, duplicate grouping,
saved searches, history, recovery and updater verification. Credential tests use
temporary synthetic entries and remove them afterward; downloads are mocked.

