#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-GNCL-1.0
# Run from a reviewed source checkout installed at /opt/gannet.
set -euo pipefail
umask 022
ONNX_RUNTIME=cpu
while [[ $# -gt 0 ]]; do
    case "$1" in
        --onnx-runtime)
            [[ $# -ge 2 ]] || { echo 'Missing --onnx-runtime cpu|cuda' >&2; exit 2; }
            ONNX_RUNTIME=$2; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
case "$ONNX_RUNTIME" in cpu|cuda) ;; *) echo 'Choose --onnx-runtime cpu or cuda' >&2; exit 2 ;; esac

if [[ ${EUID} -ne 0 ]]; then
    echo 'Run this installer as root (sudo bash scripts/install_debian.sh).' >&2
    exit 1
fi
# shellcheck source=/dev/null
source /etc/os-release
if [[ ${ID:-} != debian || ${VERSION_ID:-} != 13 || $(uname -m) != x86_64 ]]; then
    echo 'This installer supports native Debian 13 x86-64 only.' >&2
    exit 1
fi
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if [[ "$ROOT" != /opt/gannet ]]; then
    echo 'Install the reviewed source tree at /opt/gannet first; see DEBIAN.md.' >&2
    exit 1
fi
if [[ ! -d /run/systemd/system ]]; then
    echo 'A native running systemd system is required; containers are not supported.' >&2
    exit 1
fi

if systemctl is-active --quiet gannet.service; then
    systemctl stop gannet.service
fi

apt-get update
apt-get install -y ca-certificates curl ffmpeg python3-venv build-essential nodejs npm sudo wireguard-tools iproute2
if ! getent passwd gannet >/dev/null; then
    useradd --system --user-group --home-dir /var/lib/gannet --shell /usr/sbin/nologin gannet
fi
# Render/video access is sufficient for native GPU APIs. Do not run the NVR
# as root or disable kernel/device protections to make a driver work.
for group in render video; do
    if getent group "$group" >/dev/null; then usermod -aG "$group" gannet; fi
done
# The sudo helper imports code and dependencies from this tree as root. Neither
# the service account nor any non-root group may modify any of that code.
chown -R root:root "$ROOT"
chmod -R go-w "$ROOT"
chmod 0755 /opt /opt/gannet
install -d -o gannet -g gannet -m 0750 /etc/gannet /var/lib/gannet /var/cache/gannet /run/gannet
install -d -o root -g root -m 0700 /etc/wireguard /etc/wireguard/gannet

# Debian's system Python is 3.13. Do not change it or bypass PEP 668: provision
# a dedicated managed CPython 3.12 whose path is readable by the service user.
python3 -m venv /opt/gannet/.install-venv
/opt/gannet/.install-venv/bin/python -m pip install 'uv==0.13.7'
export UV_PYTHON_INSTALL_DIR=/opt/gannet/.python
export UV_CACHE_DIR=/var/cache/gannet-install
/opt/gannet/.install-venv/bin/uv python install 3.12
/opt/gannet/.install-venv/bin/uv venv --clear --python 3.12 --managed-python /opt/gannet/.venv
/opt/gannet/.install-venv/bin/uv pip install --python /opt/gannet/.venv/bin/python -r /opt/gannet/requirements-debian.txt
if [[ "$ONNX_RUNTIME" == cuda ]]; then
    # These distributions share the onnxruntime module: never install both.
    /opt/gannet/.install-venv/bin/uv pip uninstall --python /opt/gannet/.venv/bin/python onnxruntime
    /opt/gannet/.install-venv/bin/uv pip install --python /opt/gannet/.venv/bin/python 'onnxruntime-gpu[cuda,cudnn]==1.31.*'
fi
/opt/gannet/.venv/bin/python /opt/gannet/bootstrap_debian.py
(cd /opt/gannet/web && npm ci && npm run build:native)

install -d -o root -g root -m 0755 /usr/local/libexec
cat > /usr/local/libexec/gannet-wireguard <<'EOF'
#!/bin/sh
# SPDX-License-Identifier: LicenseRef-GNCL-1.0
exec /opt/gannet/.venv/bin/python -I /opt/gannet/scripts/wireguard_helper.py "$@"
EOF
chown root:root /usr/local/libexec/gannet-wireguard
chmod 0755 /usr/local/libexec/gannet-wireguard
cat > /etc/sudoers.d/gannet-wireguard <<'EOF'
# SPDX-License-Identifier: LicenseRef-GNCL-1.0
# The helper accepts only fixed lifecycle operations, validated configs and IDs.
gannet ALL=(root) NOPASSWD:NOSETENV: /usr/local/libexec/gannet-wireguard *
EOF
chmod 0440 /etc/sudoers.d/gannet-wireguard
/usr/sbin/visudo -cf /etc/sudoers.d/gannet-wireguard
chown -R gannet:gannet /etc/gannet
chown -R root:root /opt/gannet
chmod -R go-w /opt/gannet
# A root checkout may have inherited umask 077. Public runtime code, labels,
# assets and the managed interpreter must still be readable by the service.
chmod -R a+rX /opt/gannet/gannet /opt/gannet/migrations /opt/gannet/.python /opt/gannet/.venv /opt/gannet/bin /opt/gannet/web/dist /opt/gannet/docs/static
chmod a+r /opt/gannet/labelmap.txt /opt/gannet/audio-labelmap.txt

install -o root -g root -m 0644 /opt/gannet/scripts/gannet.service /etc/systemd/system/gannet.service
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/gannet.service
# Do not print generated credentials or configuration in the installer output.
sudo -u gannet env GANNET_BASE_DIR=/var/lib/gannet GANNET_CONFIG_DIR=/etc/gannet GANNET_CACHE_DIR=/var/cache/gannet GANNET_TMP_DIR=/run/gannet PATH=/opt/gannet/bin:/usr/bin:/bin /opt/gannet/.venv/bin/python -m gannet --validate-config
systemctl enable --now gannet.service
printf '\nInstalled. Inspect systemctl status gannet and journalctl -u gannet. See DEBIAN.md for access, backup, and upgrade instructions.\n'
