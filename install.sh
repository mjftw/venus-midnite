#!/bin/bash
set -euo pipefail

INSTALL_PATH="/data/midnite"
SERVICE_LINK="/service/midnite"
LOG_DIR="/var/log/midnite"
RCLOCAL="/data/rcS.local"

usage() {
    echo "Usage: $0 <cerbo-ip>"
    echo ""
    echo "  Installs venus-midnite onto a Cerbo GX / VenusOS device over SSH."
    echo "  The device will reboot at the end of installation."
    echo ""
    echo "  Example: $0 192.168.1.50"
    echo "  Example: CERBO_SSH_PASSWORD=secret $0 192.168.1.50"
    exit 1
}

[ $# -eq 1 ] || usage
CERBO_IP="$1"

if [ -n "${CERBO_SSH_PASSWORD:-}" ]; then
    if ! command -v sshpass &>/dev/null; then
        echo "ERROR: CERBO_SSH_PASSWORD is set but sshpass is not installed."
        echo "       Install it with: apt install sshpass  (or brew install hudochenkov/sshpass/sshpass on macOS)"
        exit 1
    fi
    SSH="sshpass -e ssh -o StrictHostKeyChecking=no root@${CERBO_IP}"
    SCP="sshpass -e scp -o StrictHostKeyChecking=no -r"
    export SSHPASS="${CERBO_SSH_PASSWORD}"
    echo "==> Using password authentication (sshpass)"
else
    SSH="ssh root@${CERBO_IP}"
    SCP="scp -r"
fi

echo "==> Connecting to VenusOS device at ${CERBO_IP}..."
$SSH "echo '    Connected OK'" || {
    echo "ERROR: Could not connect to root@${CERBO_IP}. Check the IP and that SSH is enabled."
    exit 1
}

echo "==> Copying files to ${INSTALL_PATH}..."
$SSH "mkdir -p ${INSTALL_PATH}/service/log"
$SCP midnite_hydro.py  "root@${CERBO_IP}:${INSTALL_PATH}/"
$SCP midnite_hydro.sh  "root@${CERBO_IP}:${INSTALL_PATH}/"
$SCP config.py         "root@${CERBO_IP}:${INSTALL_PATH}/"
$SCP service/run       "root@${CERBO_IP}:${INSTALL_PATH}/service/run"
$SCP service/log/run   "root@${CERBO_IP}:${INSTALL_PATH}/service/log/run"

echo "==> Setting permissions..."
$SSH "chmod +x ${INSTALL_PATH}/midnite_hydro.sh \
                ${INSTALL_PATH}/service/run \
                ${INSTALL_PATH}/service/log/run"

echo "==> Creating log directory..."
$SSH "mkdir -p ${LOG_DIR}"

echo "==> Registering runit service..."
$SSH "ln -sf ${INSTALL_PATH}/service ${SERVICE_LINK}"

echo "==> Adding startup hook to ${RCLOCAL}..."
$SSH "bash -c '
    if ! grep -q \"${SERVICE_LINK}\" ${RCLOCAL} 2>/dev/null; then
        echo \"\" >> ${RCLOCAL}
        echo \"# venus-midnite\" >> ${RCLOCAL}
        echo \"mkdir -p ${LOG_DIR}\" >> ${RCLOCAL}
        echo \"ln -sf ${INSTALL_PATH}/service ${SERVICE_LINK}\" >> ${RCLOCAL}
        echo \"    Added startup entries to ${RCLOCAL}\"
    else
        echo \"    Startup entries already present in ${RCLOCAL}, skipping\"
    fi
'"

echo ""
echo "    Installation complete."
echo ""
echo "    MidNite IP and poll interval are configured in:"
echo "    ${INSTALL_PATH}/config.py"
echo ""
echo "The system will now restart..."
echo ""
$SSH "reboot" || true
