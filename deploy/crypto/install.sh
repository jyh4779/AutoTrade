#!/usr/bin/env bash
set -euo pipefail
# Run from the extracted package. Deliberately does not start or enable trading.
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
id ml-crypto >/dev/null 2>&1 || useradd --system --home /var/lib/ml-crypto --shell /usr/sbin/nologin ml-crypto
install -d -o ml-crypto -g ml-crypto -m 700 /var/lib/ml-crypto
install -d -m 755 /opt/ml-crypto /etc/ml-crypto
if systemctl is-active --quiet ml-crypto; then
  echo 'Stop ml-crypto before replacing code'; exit 1
fi
cp -R src /opt/ml-crypto/
python3 -m venv /opt/ml-crypto/venv
/opt/ml-crypto/venv/bin/python -m pip install -r deploy/crypto/requirements.txt
install -m 644 deploy/crypto/ml-crypto.service /etc/systemd/system/ml-crypto.service
systemctl daemon-reload
echo 'Installed, NOT started. Restore verified data before enabling the service.'
