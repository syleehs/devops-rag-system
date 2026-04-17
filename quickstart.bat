@echo off
REM Quick start script for DevOps RAG System local development (Windows)
REM Usage: quickstart.bat

setlocal enabledelayedexpansion

echo ================================
echo DevOps RAG System - Quick Start
echo ================================
echo.

REM Check Python
echo Checking dependencies...
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python 3 is not installed
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [OK] %PYTHON_VERSION%

REM Check Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo X Docker is not installed
    exit /b 1
)
for /f "tokens=*" %%i in ('docker --version') do set DOCKER_VERSION=%%i
echo [OK] %DOCKER_VERSION%

REM Create virtual environment
echo.
echo Setting up Python virtual environment...
if not exist "venv" (
    python -m venv venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo.
echo Installing Python dependencies...
python -m pip install --quiet --upgrade pip
pip install --quiet -r backend\requirements.txt
echo [OK] Dependencies installed

REM Create .env file
echo.
echo Setting up environment variables...
if not exist ".env" (
    copy .env.example .env
    echo [OK] .env file created from template
    echo [WARNING] IMPORTANT: Edit .env and add your ANTHROPIC_API_KEY
) else (
    echo [OK] .env file already exists
)

REM Start PostgreSQL
echo.
echo Starting PostgreSQL with Docker Compose...
docker-compose up -d postgres
echo [OK] PostgreSQL started

REM Wait for PostgreSQL
echo.
echo Waiting for PostgreSQL to be ready...
timeout /t 5 /nobreak

REM Print next steps
echo.
echo ================================
echo [SUCCESS] Setup Complete!
echo ================================
echo.
echo Next steps:
echo.
echo 1. Edit .env and add your ANTHROPIC_API_KEY:
echo    notepad .env
echo.
echo 2. Start the FastAPI server:
echo    cd backend
echo    uvicorn main:app --reload
echo.
echo 3. In another terminal, test the API:
echo    curl http://localhost:8000/health
echo.
echo 4. Ingest a document:
echo    curl -X POST http://localhost:8000/ingest ^
echo      -H "Content-Type: application/json" ^
echo      -d "{\"title\": \"Test\", \"content\": \"Test content\", \"category\": \"test\"}"
echo.
echo 5. Query the knowledge base:
echo    curl -X POST http://localhost:8000/query ^
echo      -H "Content-Type: application/json" ^
echo      -d "{\"query\": \"test\"}"
echo.
echo ================================
echo.
endlocal
