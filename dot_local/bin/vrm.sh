#!/bin/bash

readonly JUMP_HOST="jump-aliyun"
readonly TARGET_HOST="homeserver"
readonly TARGET_VM_IP="192.168.122.100"
readonly LOCAL_PORT="33389"
readonly RDP_FILE_PATH="/tmp/win10_$(date +%s).rdp"
readonly SSH_SOCKET_PATH="/tmp/ssh_tunnel_win10_$(date +%s).sock"

cleanup() {
    if [[ -S "${SSH_SOCKET_PATH}" ]]; then
        # Send exit command to the master SSH process via the control socket
        if ! ssh -S "${SSH_SOCKET_PATH}" -O exit "${JUMP_HOST}" 2>/dev/null; then
            echo "Warning: Failed to cleanly close SSH control socket." >&2
        fi
    fi

    if [[ -f "${RDP_FILE_PATH}" ]]; then
        rm -f "${RDP_FILE_PATH}"
    fi
}

check_dependencies() {
    local cmd
    for cmd in ssh open; do
        if ! command -v "${cmd}" >/dev/null 2>&1; then
            echo "Error: Required dependency '${cmd}' not found." >&2
            return 1
        fi
    done
}

establish_tunnel() {
    echo "Establishing SSH tunnel via ${JUMP_HOST} -> ${TARGET_HOST}..." >&2

    # -f: Fork to background
    # -N: Do not execute a remote command
    # -M: Place the ssh client into "master" mode for connection sharing
    # -S: Specify the path to the control socket
    # -J: Jump host proxy
    # -L: Local port forwarding
    if ! ssh -f -N -M -S "${SSH_SOCKET_PATH}" \
        -J "${JUMP_HOST}" \
        -L "${LOCAL_PORT}:${TARGET_VM_IP}:3389" \
        "root@${TARGET_HOST}"; then
        echo "Error: Failed to establish SSH tunnel." >&2
        return 1
    fi
}

generate_rdp_file() {
    echo "Generating dynamic RDP configuration..." >&2

    # Write RDP configuration optimized for macOS client
    if ! cat <<EOF > "${RDP_FILE_PATH}"; then
full address:s:127.0.0.1:${LOCAL_PORT}
prompt for credentials:i:1
screen mode id:i:2
use multimon:i:0
compression:i:1
audiomode:i:0
redirectdrives:i:1
drivestoredirect:s:*
redirectprinters:i:0
smoothfonts:i:1
username:s:Administrator
EOF
        echo "Error: Failed to write RDP file to ${RDP_FILE_PATH}" >&2
        return 1
    fi
}

launch_rdp_client() {
    echo "Launching Microsoft Remote Desktop..." >&2

    # Rely on macOS Launch Services to handle the .rdp extension
    if ! open "${RDP_FILE_PATH}"; then
        echo "Error: Failed to open RDP file." >&2
        return 1
    fi
}

wait_for_user() {
    echo "---------------------------------------------------" >&2
    echo "Secure Tunnel Established & RDP Client Launched." >&2
    echo "Press [ENTER] to terminate session and cleanup..." >&2
    echo "---------------------------------------------------" >&2
    
    if ! read -r; then
        echo "Error: Failed to read user input." >&2
        return 1
    fi
}

main() {
    trap cleanup EXIT SIGINT

    if ! check_dependencies; then
        exit 1
    fi

    if ! establish_tunnel; then
        exit 1
    fi

    if ! generate_rdp_file; then
        exit 1
    fi

    if ! launch_rdp_client; then
        exit 1
    fi

    wait_for_user
}

main "$@"
