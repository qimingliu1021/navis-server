# Navis Server

Itinerary generation API using Google Gemini AI.

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Google API key
```

## Run

```bash
python src/api_server.py
```

Server starts at `http://localhost:5500`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/interests` | Get interest categories |
| POST | `/api/generate-itinerary` | Generate itinerary |
| POST | `/api/generate-itinerary-stream` | SSE streaming |
| POST | `/api/edit-itinerary` | Edit activities |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `API_PORT` | Server port | 5500 |
| `GOOGLE_API_KEY` | Google Gemini API key | Required |
| `GEMINI_MODEL` | Model name | gemini-3-pro-preview |
