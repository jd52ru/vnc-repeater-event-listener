#!/bin/bash

set -e

echo "Installing VNC Repeater Event Listener..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$PROJECT_ROOT/bin"
UVNC_REPEATER_DIR="$PROJECT_ROOT/uvncrepeater"

cd "$PROJECT_ROOT"

# Check if Python3 is installed
if ! command -v python3 &> /dev/null; then
    print_error "python3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Check if g++ is installed
if ! command -v g++ &> /dev/null; then
    print_error "g++ is not installed. Please install."
    exit 1
fi

# Check if make is installed
if ! command -v make &> /dev/null; then
    print_error "make is not installed. Please install."
    exit 1
fi

# Check if port 80 is available (requires root)
if ! lsof -i :80 > /dev/null 2>&1; then
    print_info "Port 80 is available."
else
    print_warning "Port 80 is already in use. The server may not start properly."
fi

# Check if we're running as root for system operations
if [ "$EUID" -ne 0 ]; then
    print_error "Please run this script as root (use sudo) for system installation"
    exit 1
fi

# Create system user for both services
print_warning "The installation will create a system user 'uvncrep' for running both UltraVNC Repeater and Event Listener services."
read -p "Do you want to continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Installation cancelled by user"
    exit 1
fi

print_info "Creating system user 'uvncrep'..."
if id "uvncrep" &>/dev/null; then
    print_warning "User uvncrep already exists"
else
    useradd -r -s /bin/false -d "$BIN_DIR" -c "UltraVNC Repeater and Event Listener" uvncrep
    if [ $? -eq 0 ]; then
        print_success "System user uvncrep created"
    else
        print_error "Failed to create user uvncrep"
        exit 1
    fi
fi

# Install UltraVNC Repeater
print_info "Installing UltraVNC Repeater..."

if [ -d "$UVNC_REPEATER_DIR" ]; then
    cd "$UVNC_REPEATER_DIR"

    # Build the repeater
    if [ -f "Makefile" ]; then
        print_info "Building UltraVNC Repeater..."
        make clean
        if make; then
            print_success "UltraVNC Repeater built successfully"
        else
            print_error "Failed to build UltraVNC Repeater!"
            exit 1
        fi
    else
        print_error "Makefile not found in $UVNC_REPEATER_DIR"
        exit 1
    fi

    # Create configuration directory
    print_info "Creating configuration directory..."
    if test -d /etc/uvnc ; then
        print_warning "/etc/uvnc directory already exists."
    else
        mkdir /etc/uvnc
        print_success "Configuration directory created"
    fi

    # Copy configuration file
    print_info "Installing configuration file..."
    if [ -f /etc/uvnc/uvncrepeater.ini ]; then
        print_warning "uvncrepeater.ini already exists - will not overwrite!" 
    else
        if [ -f uvncrepeater.ini ]; then
            cp uvncrepeater.ini /etc/uvnc
            print_success "Configuration file installed"
        else
            print_warning "uvncrepeater.ini not found, creating default..."
            # Create default configuration for event listener integration
            cat > /etc/uvnc/uvncrepeater.ini << 'EOF'
[general]
viewerport=5900
serverport=5500
maxsessions=100
allowedmodes=2
ownipaddress=0.0.0.0
runasuser=uvncrep
logginglevel=2

[mode1]
allowedmode1serverport=0
requirelistedserver=0

[mode2]
requirelistedid=0

[eventinterface]
useeventinterface=1
eventlistenerhost=127.0.0.1
eventlistenerport=80
usehttp=1
EOF
            print_success "Default configuration file created"
        fi
    fi

    # Install binary
    print_info "Installing repeater binary..."
    cp repeater /usr/sbin/uvncrepeatersvc
    if [ $? -eq 0 ]; then
        print_success "Binary installed to /usr/sbin/uvncrepeatersvc"
    else
        print_error "Failed to install binary!"
        exit 1
    fi

    cd "$PROJECT_ROOT"
else
    print_warning "UltraVNC Repeater directory not found at $UVNC_REPEATER_DIR"
    print_warning "Skipping UltraVNC Repeater installation"
fi

# Create virtual environment for event listener
print_info "Creating virtual environment for event listener..."
python3 -m venv venv

# Activate virtual environment
print_info "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
print_info "Upgrading pip..."
pip install --upgrade pip

# Install requirements
print_info "Installing Python dependencies..."
pip install -r requirements.txt

# Set ownership of project directory to uvncrep user
chown -R uvncrep:uvncrep "$PROJECT_ROOT"
chmod 755 "$BIN_DIR"

# Create log directory
print_info "Creating log directory..."
if [ ! -d /var/log/uvnc ]; then
    mkdir -p /var/log/uvnc
    chown uvncrep:uvncrep /var/log/uvnc
    print_success "Log directory created"
fi

# Set permissions on config file (if repeater was installed)
if [ -f "/etc/uvnc/uvncrepeater.ini" ]; then
    chown uvncrep:uvncrep /etc/uvnc/uvncrepeater.ini
    chmod 644 /etc/uvnc/uvncrepeater.ini
fi

if [ -f "/usr/sbin/uvncrepeatersvc" ]; then
    chmod 755 /usr/sbin/uvncrepeatersvc
fi

# Create systemd service file for event listener
print_info "Creating systemd service for event listener..."
cat > /etc/systemd/system/uvnc-event-listener.service << EOF
[Unit]
Description=UltraVNC Repeater Event Listener
After=network.target
Wants=uvncrepeater.service

[Service]
Type=simple
User=uvncrep
Group=uvncrep
WorkingDirectory=$BIN_DIR
Environment=PYTHONPATH=$PROJECT_ROOT/venv/lib/python3.*/site-packages
Environment=FLASK_APP=app.py
ExecStart=$PROJECT_ROOT/venv/bin/python app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security settings for port 80 binding
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$BIN_DIR /var/log/uvnc /tmp

[Install]
WantedBy=multi-user.target
EOF

# Create systemd service file for UltraVNC Repeater (only if installed)
if [ -f "/usr/sbin/uvncrepeatersvc" ]; then
    print_info "Creating systemd service for UltraVNC Repeater..."
    cat > /etc/systemd/system/uvncrepeater.service << EOF
[Unit]
Description=UltraVNC Repeater Service
After=network.target

[Service]
Type=simple
User=uvncrep
Group=uvncrep
ExecStart=/usr/sbin/uvncrepeatersvc /etc/uvnc/uvncrepeater.ini
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/etc/uvnc /tmp

[Install]
WantedBy=multi-user.target
EOF
fi

systemctl daemon-reload

# Enable and start services
print_info "Enabling and starting services..."

if systemctl enable uvnc-event-listener.service; then
    print_success "Event listener service enabled"
else
    print_error "Failed to enable event listener service"
    exit 1
fi

if [ -f "/usr/sbin/uvncrepeatersvc" ] && systemctl enable uvncrepeater.service 2>/dev/null; then
    print_success "UltraVNC Repeater service enabled"
else
    print_warning "UltraVNC Repeater service not enabled (may not be installed)"
fi

print_info "Starting services..."

if systemctl start uvnc-event-listener.service; then
    print_success "Event listener service started"
else
    print_error "Failed to start event listener service"
    print_info "Check status with: systemctl status uvnc-event-listener.service"
fi

if [ -f "/usr/sbin/uvncrepeatersvc" ] && systemctl start uvncrepeater.service 2>/dev/null; then
    print_success "UltraVNC Repeater service started"
else
    print_warning "UltraVNC Repeater service not started (may not be installed)"
fi

print_success "Installation completed successfully!"
echo
echo -e "${BLUE}Installation Summary:${NC}"
echo -e "  ${GREEN}✓${NC} Event Listener: $BIN_DIR/app.py"
echo -e "  ${GREEN}✓${NC} Virtual Environment: $PROJECT_ROOT/venv"
echo -e "  ${GREEN}✓${NC} Service User: uvncrep"
echo -e "  ${GREEN}✓${NC} Service: uvnc-event-listener (port 80)"
if [ -f "/usr/sbin/uvncrepeatersvc" ]; then
    echo -e "  ${GREEN}✓${NC} UltraVNC Repeater: /usr/sbin/uvncrepeatersvc"
    echo -e "  ${GREEN}✓${NC} Repeater Config: /etc/uvnc/uvncrepeater.ini"
fi
echo
echo -e "${BLUE}Service Management:${NC}"
echo -e "  Event Listener:"
echo -e "    Start:    ${GREEN}systemctl start uvnc-event-listener${NC}"
echo -e "    Stop:     ${GREEN}systemctl stop uvnc-event-listener${NC}"
echo -e "    Status:   ${GREEN}systemctl status uvnc-event-listener${NC}"
echo -e "    Logs:     ${GREEN}journalctl -u uvnc-event-listener -f${NC}"
if [ -f "/usr/sbin/uvncrepeatersvc" ]; then
    echo -e "  UltraVNC Repeater:"
    echo -e "    Start:    ${GREEN}systemctl start uvncrepeater${NC}"
    echo -e "    Stop:     ${GREEN}systemctl stop uvncrepeater${NC}"
    echo -e "    Status:   ${GREEN}systemctl status uvncrepeater${NC}"
    echo -e "    Logs:     ${GREEN}journalctl -u uvncrepeater -f${NC}"
fi
echo
echo -e "${YELLOW}Important Notes:${NC}"
echo -e "  • Both services run as user ${BLUE}uvncrep${NC}"
echo -e "  • Event listener uses ${BLUE}CAP_NET_BIND_SERVICE${NC} for port 80"
echo -e "  • UltraVNC Repeater sends events to ${BLUE}127.0.0.1:80${NC}"
echo -e "  • Web interface available at: ${GREEN}http://your-server-ip${NC}"
echo
echo -e "${GREEN}Services are now running and integrated!${NC}"
