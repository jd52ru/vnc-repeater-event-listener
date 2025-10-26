#!/bin/bash

set -e

echo "Uninstalling VNC Repeater Event Listener..."

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

# Check if we're running as root for system operations
if [ "$EUID" -ne 0 ]; then
    print_error "Please run this script as root (use sudo) for system uninstallation"
    exit 1
fi

cd "$PROJECT_ROOT"

print_info "Stopping services..."
systemctl stop uvnc-event-listener.service 2>/dev/null || print_warning "Event listener service not running or not found"
systemctl stop uvncrepeater.service 2>/dev/null || print_warning "UltraVNC Repeater service not running or not found"

print_info "Disabling services..."
systemctl disable uvnc-event-listener.service 2>/dev/null || print_warning "Event listener service not found"
systemctl disable uvncrepeater.service 2>/dev/null || print_warning "UltraVNC Repeater service not found"

print_info "Removing systemd service files..."
rm -f /etc/systemd/system/uvnc-event-listener.service
rm -f /etc/systemd/system/uvncrepeater.service
systemctl daemon-reload
systemctl reset-failed

# Remove UltraVNC Repeater components
print_info "Removing UltraVNC Repeater components..."

if [ -f "/usr/sbin/uvncrepeatersvc" ]; then
    rm -f /usr/sbin/uvncrepeatersvc
    print_success "UltraVNC Repeater binary removed"
else
    print_warning "UltraVNC Repeater binary not found"
fi

# Ask about configuration files
read -p "Remove UltraVNC Repeater configuration files in /etc/uvnc? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf /etc/uvnc
    print_success "UltraVNC Repeater configuration files removed"
else
    print_warning "UltraVNC Repeater configuration files preserved in /etc/uvnc"
fi

# Ask about log files
read -p "Remove log files in /var/log/uvnc? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf /var/log/uvnc
    print_success "Log files removed"
else
    print_warning "Log files preserved in /var/log/uvnc"
fi

# Ask about database files
read -p "Remove database files in /tmp/repeater_events.db? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f /tmp/repeater_events.db
    rm -f /tmp/repeater_events.db-journal
    print_success "Database files removed"
else
    print_warning "Database files preserved in /tmp/"
fi

# Ask about system user
if id "uvncrep" &>/dev/null; then
    print_warning "System user 'uvncrep' was created during installation"
    read -p "Remove system user 'uvncrep'? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        userdel uvncrep 2>/dev/null && print_success "User uvncrep removed" || print_error "Failed to remove user uvncrep"
    else
        print_warning "User uvncrep preserved"
    fi
else
    print_warning "User uvncrep not found"
fi

# Ask about virtual environment
read -p "Remove Python virtual environment? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -d "venv" ]; then
        rm -rf venv
        print_success "Virtual environment removed"
    else
        print_warning "Virtual environment not found"
    fi
else
    print_warning "Virtual environment preserved"
fi

# Ask about project files
print_warning "Project files are located in: $PROJECT_ROOT"
read -p "Remove all project files? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_warning "This will remove the entire project directory: $PROJECT_ROOT"
    read -p "Are you absolutely sure? This cannot be undone! (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd /
        rm -rf "$PROJECT_ROOT"
        print_success "Project files removed"
    else
        print_warning "Project files preserved"
    fi
else
    print_warning "Project files preserved"
fi

print_success "Uninstallation completed!"
echo
echo -e "${YELLOW}Note:${NC} Some components may have been preserved based on your choices."
echo -e "You can manually remove any remaining components if needed."
echo
echo -e "${BLUE}Remaining components (if any):${NC}"
echo -e "  • Configuration: /etc/uvnc/"
echo -e "  • Logs: /var/log/uvnc/"
echo -e "  • Database: /tmp/repeater_events.db"
echo -e "  • User: uvncrep"
echo -e "  • Project: $PROJECT_ROOT"
