# Local Dev env setup

## Prerequisites

1. Get a fresh new WSL machine up:

   ```powershell
   # Delete old WSL
   wsl --unregister Ubuntu-24.04

   # Create new WSL
   wsl --install -d Ubuntu-24.04
   ```

1. Clone the repo, and open VSCode in it:

   ```bash
   cd ~/

   git config --global user.name "Raki Rahman"
   git config --global user.email "mdrakiburrahman@gmail.com"
   git clone https://github.com/mdrakiburrahman/sqlglot.git

   cd sqlglot/
   code .
   ```

1. Run the bootstrapper script, that installs all tools idempotently:

   ```bash
   GIT_ROOT=$(git rev-parse --show-toplevel)
   chmod +x ${GIT_ROOT}/contrib/bootstrap-dev-env.sh && ${GIT_ROOT}/contrib/bootstrap-dev-env.sh && source ~/.bashrc
   ```

## Install

Initialize Virtual Env:

```bash
python3 -m venv .venv
source ./.venv/bin/activate
```

```bash
make install
make install-dev
```

## Tests

Full GCI:

```bash
make check
```

## Build and upload to ADO

```bash
pip install build twine
python -m build
```

The `whl` will be available here: `~/sqlglot/dist/sqlglot-0.1.dev5757-py3-none-any.whl`.

It can be installed with `pip install --force-reinstall path/to/your/package.whl`