#!/bin/bash

# Usage: wanke_tunnel <HOST> <TYPE> <PORT> <QOS> <BIND_MODE>
# 
# Arguments:
#   1. HOST:        Target SSH alias (wanke, win-server)
#   2. TYPE:        -L (Local Forward) or -D (Dynamic/SOCKS)
#   3. PORT:        Port specification (e.g., 7893:localhost:7893 or 1080)
#   4. QOS:         lowdelay, none, throughput
#   5. BIND_MODE:   'bind' (force specific interface) or 'nobind' (let OS decide)

TARGET_HOST="$1"
TUNNEL_TYPE="$2"
PORT_SPEC="$3"
QOS_LEVEL="$4"
BIND_MODE="$5"

# 1. Validation
if [[ -z "$BIND_MODE" ]]; then
    echo "Error: Missing arguments."
    echo "Usage: $0 <HOST> <TYPE> <PORT> <QOS> <bind|nobind>"
    exit 1
fi

# 2. Build the Command Array
# We start with the base command and mandatory options
CMD=( /usr/bin/ssh -N )

# 3. Handle Binding Logic
if [[ "$BIND_MODE" == "bind" ]]; then
    # Interface Priority List
    INTERFACES=("en8" "en0" "en1" "en7" "en5")
    FOUND_IP=""
    
    echo "🔍 Mode: BIND. Searching for active interface..."
    
    for iface in "${INTERFACES[@]}"; do
        CURRENT_IP=$(ipconfig getifaddr "$iface")
        if [[ -n "$CURRENT_IP" ]]; then
            FOUND_IP="$CURRENT_IP"
            echo "✅ Found active connection on $iface ($FOUND_IP)"
            break
        fi
    done

    if [[ -z "$FOUND_IP" ]]; then
        echo "❌ Error: No active IP found on interfaces: ${INTERFACES[*]}"
        exit 1
    fi
    
    # Add the binding flag to our command array
    CMD+=( -b "$FOUND_IP" )

elif [[ "$BIND_MODE" == "nobind" ]]; then
    echo "🌐 Mode: NOBIND. Letting macOS routing table decide connection path."
else
    echo "❌ Error: Invalid BIND_MODE '$BIND_MODE'. Must be 'bind' or 'nobind'."
    exit 1
fi

# 4. Add remaining options
CMD+=( -o "ControlMaster=no" )
CMD+=( -o "ExitOnForwardFailure=yes" )
CMD+=( -o "ServerAliveInterval=15" )
CMD+=( -o "ServerAliveCountMax=3" )
CMD+=( -o "IPQoS=$QOS_LEVEL" )
CMD+=( "$TUNNEL_TYPE" "$PORT_SPEC" )
CMD+=( "$TARGET_HOST" )

# 5. Execute
echo "🚀 Executing SSH..."
exec "${CMD[@]}"
