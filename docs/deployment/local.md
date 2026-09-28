# Running Locally

A local run is the right choice for development, for a quick test before committing to
Docker, or on a host where you do not want a container runtime. For anything long-lived,
[Docker](docker.md) is less to maintain.

You need **Python 3.12**. That is what the image is built on (`python:3.12-slim`) and what
CI tests against.

## Install

```bash
git clone https://github.com/nichtlegacy/MediaWatch.git
cd MediaWatch
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Use a virtual environment. `requirements.txt` pins upper bounds per dependency
(`discord.py>=2.4,<3.0` and friends), and installing that into a system Python is how you
break an unrelated project.

## Configure

Same two files as everywhere else:

```bash
cp .env.example .env
cp data/config.yaml.example data/config.yaml
```

Fill them in as described in [First run](../getting-started/first-run.md). A local run
reads `.env` through `python-dotenv`, without `RUNNING_IN_DOCKER` or `env_file`.

## Start

```bash
python main.py
```

!!! warning "A local run prints nothing to the console"
    This surprises everyone once. Outside Docker the logger has **no** console handler:
    all output goes to `logs/mediawatch_debug.log`, rotated at midnight, the current
    file plus seven dated ones (`mediawatch_debug.log.2026-09-06` and so on). A terminal that just sits there is the
    normal, working state, not a hang.

    ```bash
    tail -f logs/mediawatch_debug.log
    ```

The exceptions are the three reasons the bot refuses to start: missing environment
variables, an unusable `config.yaml` (`Bot stopped: …`) and a failed 1.x conversion
(`Config migration failed. Bot stopped. …`). Each is raised as the `SystemExit` message,
so it lands on stderr and you see it in the terminal even though everything else does not.

## Two path gotchas

**Start it from the repository root.** The log directory is resolved relative to the
current working directory, so `cd /somewhere/else && python /path/to/MediaWatch/main.py`
creates `/somewhere/else/logs/` and writes there. Cogs and `data/config.yaml` are resolved
relative to `main.py` and are not affected; only the log path is.

**Windows works.** `main.py` switches to the selector event loop policy on Windows before
anything else runs; you do not have to do anything for it.

## Keeping it running

`python main.py` in a terminal ends when the terminal does. If you want it to survive a
logout or a reboot, use a service manager. Create the account first and give it the checkout:

```bash
sudo useradd --system --no-create-home mediawatch
sudo chown -R mediawatch: /opt/MediaWatch
```

Minimal systemd unit:

```ini
# /etc/systemd/system/mediawatch.service
[Unit]
Description=MediaWatch Discord bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=mediawatch
WorkingDirectory=/opt/MediaWatch
ExecStart=/opt/MediaWatch/.venv/bin/python main.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` is not optional; see the path gotcha above. `journalctl -u mediawatch`
will still be near-empty; the log file remains the place to look.

## Updating a local install

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt      # in case a pin moved
```

Then restart the process. `.env` and the files the bot writes into `data/` are ignored by
git, so a `git pull` never touches them; it only updates `data/config.yaml.example`. More detail, including rollback, in [Updating](updating.md).
