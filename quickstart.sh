#!/bin/bash
# Quick start script for DevOps RAG System local development
# Usage: bash quickstart.sh

set -e

echo "================================"
echo "DevOps RAG System - Quick Start"
echo "================================"

# Check dependencies
echo ""
echo "Checking dependencies..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed"
    exit 1
fi
echo "✓ Docker found: $(docker --version)"

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed"
    exit 1
fi
echo "✓ Docker Compose found: $(docker-compose --version)"

# Create virtual environment
echo ""
echo "Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo ""
echo "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt
echo "✓ Dependencies installed"

# Create .env file
echo ""
echo "Setting up environment variables..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ .env file created from template"
    echo "⚠️  IMPORTANT: Edit .env and add your ANTHROPIC_API_KEY"
else
    echo "✓ .env file already exists"
fi

# Start PostgreSQL
echo ""
echo "Starting PostgreSQL with Docker Compose..."
docker-compose up -d postgres
echo "✓ PostgreSQL started"

# Wait for PostgreSQL to be ready
echo ""
echo "Waiting for PostgreSQL to be ready..."
sleep 5
until docker-compose exec -T postgres pg_isready -U postgres &> /dev/null; do
    echo "  Waiting for database..."
    sleep 2
done
echo "✓ PostgreSQL is ready"

# Print next steps
echo ""
echo "================================"
echo "✅ Setup Complete!"
echo "================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit .env and add your ANTHROPIC_API_KEY:"
echo "   nano .env"
echo ""
echo "2. Start the FastAPI server:"
echo "   cd backend"
echo "   uvicorn main:app --reload"
echo ""
echo "3. In another terminal, test the API:"
echo "   curl http://localhost:8000/health"
echo ""
echo "4. Ingest a document:"
echo "   curl -X POST http://localhost:8000/ingest \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"title\": \"Test\", \"content\": \"Test content\", \"category\": \"test\"}'"
echo ""
echo "5. Query the knowledge base:"
echo "   curl -X POST http://localhost:8000/query \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"query\": \"test\"}'"
echo ""
echo "================================"
