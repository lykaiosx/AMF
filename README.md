# AMF 4.9

Run **INSTALL.cmd** (or Setup.exe) from this complete folder. Keep `payload`,
`runtime_setup.ps1`, and `pip.pyz` beside the installer. No manual Python setup,
administrator access, or ZIP creation is required.

Supported target: 64-bit Windows 10 version 1809 or later, and Windows 11.
32-bit Windows and older Windows versions are not supported by the current Qt UI.
ARM devices require Windows x64 application emulation; native ARM is not tested.
First installation requires internet access to python.org and pypi.org and their
download hosts. Allow several minutes for the UI libraries to download.

Setup installs a private Python 3.13.7 runtime and pinned direct dependencies in
`%LOCALAPPDATA%\Programs\AMF`. It does not depend on Microsoft Store Python aliases
or change system Python. Python and the bundled official PyPA pip zipapp are
checked with SHA-256 before use. Pip and its included license notices are from
https://bootstrap.pypa.io/pip/pip.pyz.

Setup verifies imports, the application version and window construction before
replacing application files and registering shortcuts. Existing settings and cart
files are preserved. Launch AMF from the Start menu after installation.

If setup fails, retain the full `dependencies.log`, `dependencies-error.log`,
`install-check.log`, `install-check-error.log`, and `setup-error.log` from the
installation folder. A network interruption can be retried by running setup again.
Application launch errors are saved in `startup-error.log` in that folder.

4.9 fixes a mismatched installer/app version and PowerShell stopping at the first
line of Python stderr instead of installing missing dependencies. It supplies its
own runtime rather than relying on Python installed on another computer.
