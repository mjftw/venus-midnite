#!/bin/bash
set -euo pipefail

INSTALL_PATH="/data/midnite"
SERVICE_LINK="/service/midnite"
LOG_DIR="/var/log/midnite"
RCLOCAL="/data/rcS.local"

CONNECT_RETRIES=50
CONNECT_RETRY_DELAY=3  # seconds between attempts

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
    SCP="sshpass -e scp -o StrictHostKeyChecking=no"
    export SSHPASS="${CERBO_SSH_PASSWORD}"
    echo "==> Using password authentication (sshpass)"
else
    SSH="ssh root@${CERBO_IP}"
    SCP="scp"
fi

# Retry wrapper for SSH connections
ssh_with_retry() {
    local attempt=1
    until $SSH "$1"; do
        if [ $attempt -ge $CONNECT_RETRIES ]; then
            echo "ERROR: Could not connect to root@${CERBO_IP} after ${CONNECT_RETRIES} attempts."
            echo "       Check the IP address and that SSH is enabled on the device."
            exit 1
        fi
        echo "    Connection failed (attempt ${attempt}/${CONNECT_RETRIES}), retrying in ${CONNECT_RETRY_DELAY}s..."
        sleep $CONNECT_RETRY_DELAY
        attempt=$((attempt + 1))
    done
}

# scp a single file with progress logging
scp_file() {
    local src="$1"
    local dest="$2"
    echo "    ${src} -> ${dest}"
    $SCP "$src" "root@${CERBO_IP}:${dest}"
}

echo "==> Connecting to VenusOS device at ${CERBO_IP}..."
ssh_with_retry "echo '    Connected OK'"

echo "==> Copying files to ${INSTALL_PATH}..."
$SSH "mkdir -p ${INSTALL_PATH}/service/log"
scp_file midnite_classic.py  "${INSTALL_PATH}/midnite_classic.py"
scp_file midnite_classic.sh  "${INSTALL_PATH}/midnite_classic.sh"
scp_file config.py         "${INSTALL_PATH}/config.py"
scp_file service/run       "${INSTALL_PATH}/service/run"
scp_file service/log/run   "${INSTALL_PATH}/service/log/run"

echo "==> Setting permissions..."
$SSH "chmod +x ${INSTALL_PATH}/midnite_classic.sh \
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
