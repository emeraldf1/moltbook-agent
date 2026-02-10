#!/bin/bash
#
# install.sh - Moltbook Agent telepítő script Hostinger VPS-re (Ubuntu 22.04)
#
# Használat:
#   chmod +x deploy/install.sh
#   sudo ./deploy/install.sh
#
# Mit csinál:
#   1. Telepíti a Python 3.11-et és függőségeket
#   2. Létrehozza a moltbook felhasználót
#   3. Beállítja a projektet /opt/moltbook-agent alatt
#   4. Telepíti a systemd service-t
#   5. Elindítja az agentet
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Moltbook Agent Installer${NC}"
echo -e "${GREEN}  Hostinger VPS (Ubuntu 22.04)${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Please run as root (sudo ./install.sh)${NC}"
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${YELLOW}Project directory: $PROJECT_DIR${NC}"
echo ""

# Step 1: Update system
echo -e "${GREEN}[1/7] Updating system packages...${NC}"
apt-get update -qq
apt-get upgrade -y -qq

# Step 2: Install Python 3.11
echo -e "${GREEN}[2/7] Installing Python 3.11...${NC}"
apt-get install -y -qq software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
apt-get update -qq
apt-get install -y -qq python3.11 python3.11-venv python3.11-dev python3-pip git

# Verify Python
python3.11 --version

# Step 3: Create moltbook user
echo -e "${GREEN}[3/7] Creating moltbook user...${NC}"
if id "moltbook" &>/dev/null; then
    echo "User moltbook already exists"
else
    useradd -r -s /bin/bash -m -d /home/moltbook moltbook
    echo "User moltbook created"
fi

# Step 4: Setup project directory
echo -e "${GREEN}[4/7] Setting up project directory...${NC}"
INSTALL_DIR="/opt/moltbook-agent"

if [ -d "$INSTALL_DIR" ]; then
    echo "Directory exists, backing up..."
    mv "$INSTALL_DIR" "${INSTALL_DIR}.backup.$(date +%Y%m%d%H%M%S)"
fi

# Copy project files
cp -r "$PROJECT_DIR" "$INSTALL_DIR"

# Create virtual environment
echo -e "${GREEN}[5/7] Creating Python virtual environment...${NC}"
cd "$INSTALL_DIR"
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Verify installation
python -c "from adapters import get_adapter; print('✅ Adapters OK')"
python -c "from moltagent import should_reply; print('✅ Moltagent OK')"

# Step 6: Setup .env file
echo -e "${GREEN}[6/7] Checking .env file...${NC}"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo -e "${YELLOW}⚠️  .env file not found!${NC}"
    echo ""
    echo "Please create $INSTALL_DIR/.env with:"
    echo "  OPENAI_API_KEY=sk-..."
    echo "  MOLTBOOK_API_KEY=moltbook_sk_..."
    echo "  MOLTBOOK_AGENT_NAME=YourAgentName"
    echo "  MOLTBOOK_DRY_RUN=true"
    echo ""

    # Create template
    cat > "$INSTALL_DIR/.env.template" << 'EOF'
# Moltbook Agent Configuration
# Copy this to .env and fill in your values

OPENAI_API_KEY=sk-your-openai-key-here
MOLTBOOK_API_KEY=moltbook_sk_your-moltbook-key-here
MOLTBOOK_AGENT_NAME=YourAgentName
MOLTBOOK_DRY_RUN=true
EOF
    echo "Template created at $INSTALL_DIR/.env.template"
fi

# Set ownership
chown -R moltbook:moltbook "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true
chmod 600 "$INSTALL_DIR/.env.template" 2>/dev/null || true

# Create logs directory
mkdir -p "$INSTALL_DIR/logs"
chown moltbook:moltbook "$INSTALL_DIR/logs"

# Step 7: Install systemd service
echo -e "${GREEN}[7/7] Installing systemd service...${NC}"
cp "$INSTALL_DIR/deploy/moltbook-agent.service" /etc/systemd/system/
systemctl daemon-reload

# Enable service (but don't start yet if .env missing)
systemctl enable moltbook-agent

if [ -f "$INSTALL_DIR/.env" ]; then
    echo "Starting service..."
    systemctl start moltbook-agent
    sleep 2
    systemctl status moltbook-agent --no-pager || true
else
    echo -e "${YELLOW}⚠️  Service NOT started - .env file missing${NC}"
    echo "After creating .env, run: sudo systemctl start moltbook-agent"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status moltbook-agent    # Check status"
echo "  sudo systemctl start moltbook-agent     # Start"
echo "  sudo systemctl stop moltbook-agent      # Stop"
echo "  sudo systemctl restart moltbook-agent   # Restart"
echo "  sudo journalctl -u moltbook-agent -f    # View logs"
echo ""
echo "Configuration:"
echo "  Edit: $INSTALL_DIR/.env"
echo "  Edit: $INSTALL_DIR/policy.json"
echo ""
echo "Logs:"
echo "  $INSTALL_DIR/logs/"
echo ""

# Check if .env exists for final message
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo -e "${YELLOW}⚠️  IMPORTANT: Create .env file before starting!${NC}"
    echo "  cp $INSTALL_DIR/.env.template $INSTALL_DIR/.env"
    echo "  nano $INSTALL_DIR/.env"
    echo "  sudo systemctl start moltbook-agent"
fi
