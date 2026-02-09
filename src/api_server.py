"""
Itinerary API Server - Orchestrates Scout and Explorer
Uses modular architecture: Scout finds links, Explorer extracts events
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import json
import asyncio

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# Import modules
from scout import scout_events
from explorer import explore_links
from edit_itinerary import process_edit_request
from user_interests import INTEREST_CATEGORIES, get_all_tags, find_categories_for_interests

# Configuration
CONFIG = {
    "google_api_key": os.getenv("GOOGLE_API_KEY"),
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    "port": int(os.getenv("API_PORT", "5500")),
}

# Validate configuration
if not CONFIG["google_api_key"]:
    print("❌ GOOGLE_API_KEY is required")
    sys.exit(1)

# Create logs directory
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# FastAPI app
app = FastAPI(
    title="Navis Itinerary API",
    description="AI-powered itinerary generation using Google Gemini",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class GenerateItineraryRequest(BaseModel):
    city: str
    interests: str
    start_date: str
    end_date: str


class EditItineraryRequest(BaseModel):
    edit_request: str
    current_activity: Dict[str, Any]
    city: Optional[str] = None
    day_date: Optional[str] = None
    interests: Optional[List[str]] = None


# Logger class
class Logger:
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        # Create subfolder for this request
        self.folder_name = f"request_{self.timestamp}_{request_id}"
        self.request_dir = LOGS_DIR / self.folder_name
        self.request_dir.mkdir(exist_ok=True)
        
        # File paths
        self.log_file = self.request_dir / "console.log"
        self.scout_file = self.request_dir / "scout.json"
        self.explorer_file = self.request_dir / "explorer.json"
        self.itinerary_file = self.request_dir / "itinerary.json"
        
        self.platforms_used: set = set()
        self.data: Dict[str, Any] = {}
    
    def log(self, message: str):
        log_entry = f"[{datetime.now().isoformat()}] {message}\n"
        print(message)
        with open(self.log_file, "a") as f:
            f.write(log_entry)
    
    def log_scout_results(self, results: Dict[str, Any]):
        self.log(f"\n📊 Scout Results: {results.get('total_links_found', 0)} unique links found")
        with open(self.scout_file, "w") as f:
            json.dump(results, f, indent=2)
        self.log(f"📁 Scout results saved to: {self.folder_name}/scout.json")
    
    def log_explorer_results(self, results: Dict[str, Any]):
        self.log(f"\n📊 Explorer Results: {results.get('total_events', 0)} valid events extracted")
        
        for event in results.get("events", []):
            platform = event.get("source", {}).get("platform")
            if platform:
                self.platforms_used.add(platform)
        
        with open(self.explorer_file, "w") as f:
            json.dump(results, f, indent=2)
        self.log(f"📁 Explorer results saved to: {self.folder_name}/explorer.json")
    
    def log_final_itinerary(self, events: List[Dict[str, Any]]):
        self.log(f"\n✅ Final itinerary generated with {len(events)} events")
        
        # Clean events
        cleaned_events = []
        for event in events:
            clean_event = {k: v for k, v in event.items() if k not in ["interest_matched", "target_date"]}
            cleaned_events.append(clean_event)
        
        itinerary_output = {
            "itinerary": cleaned_events,
            "search_summary": {
                "platforms_used": list(self.platforms_used),
                "search_date": datetime.now().isoformat()
            }
        }
        
        with open(self.itinerary_file, "w") as f:
            json.dump(itinerary_output, f, indent=2)
        self.log(f"📁 Itinerary saved to: {self.folder_name}/itinerary.json")
    
    def save_all(self):
        self.log(f"\n📦 All logs saved to folder: {self.folder_name}")


def parse_interests(interests: str) -> List[str]:
    """Parse interests string into array."""
    return [i.strip() for i in interests.split(",") if i.strip()]


def analyze_event_coverage(events: List[Dict[str, Any]], start_date: str, end_date: str) -> Dict[str, Any]:
    """Ensure minimum events per day coverage."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    
    # Initialize all dates
    from datetime import timedelta
    current = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        grouped[date_str] = []
        current += timedelta(days=1)
    
    # Group events by date
    for event in events:
        if event.get("start_time"):
            event_date = event["start_time"].split("T")[0]
            if event_date in grouped:
                grouped[event_date].append(event)
    
    # Calculate coverage
    coverage = {}
    for date, day_events in grouped.items():
        def has_time_slot(events: List[Dict], start_hour: int, end_hour: int) -> bool:
            for e in events:
                try:
                    hour = int(e["start_time"].split("T")[1].split(":")[0])
                    if start_hour <= hour < end_hour:
                        return True
                except (KeyError, IndexError, ValueError):
                    pass
            return False
        
        coverage[date] = {
            "count": len(day_events),
            "events": day_events,
            "has_morning": has_time_slot(day_events, 8, 12),
            "has_afternoon": has_time_slot(day_events, 12, 17),
            "has_evening": has_time_slot(day_events, 17, 24)
        }
    
    return coverage


async def generate_itinerary(
    city: str,
    interests: List[str],
    start_date: str,
    end_date: str,
    logger: Logger
) -> Dict[str, Any]:
    """Main orchestration function - coordinates Scout and Explorer."""
    logger.log(f"\n{'=' * 60}")
    logger.log("🚀 Starting Itinerary Generation Pipeline")
    logger.log(f"{'=' * 60}")
    logger.log(f"📍 City: {city}")
    logger.log(f"🎯 Interests: {', '.join(interests)}")
    logger.log(f"📅 Dates: {start_date} to {end_date}")
    
    logger.data = {
        "city": city,
        "interests": interests,
        "start_date": start_date,
        "end_date": end_date
    }
    
    # Phase 1: Scout - Find event links
    logger.log(f"\n{'─' * 40}")
    logger.log("📡 PHASE 1: SCOUT - Finding Event Links")
    logger.log(f"{'─' * 40}")
    
    scout_results = await scout_events(city, interests, start_date, end_date, logger.log)
    logger.log_scout_results(scout_results)
    
    if not scout_results.get("all_links"):
        logger.log("⚠️ Scout found no links. Cannot proceed.")
        return {
            "success": False,
            "events": [],
            "message": "No event links found during search"
        }
    
    # Phase 2: Explorer - Analyze links and extract events
    logger.log(f"\n{'─' * 40}")
    logger.log("🔬 PHASE 2: EXPLORER - Analyzing Links")
    logger.log(f"{'─' * 40}")
    
    explorer_results = await explore_links(scout_results["all_links"], city, logger.log)
    logger.log_explorer_results(explorer_results)
    
    # Phase 3: Organize and validate events
    logger.log(f"\n{'─' * 40}")
    logger.log("📋 PHASE 3: ORGANIZING EVENTS")
    logger.log(f"{'─' * 40}")
    
    events = explorer_results.get("events", [])
    
    # Sort by start_time
    events.sort(key=lambda e: e.get("start_time", "2099-01-01T00:00:00"))
    
    # Analyze coverage
    coverage = analyze_event_coverage(events, start_date, end_date)
    
    # Log coverage summary
    for date, info in coverage.items():
        morning = "✓" if info["has_morning"] else "✗"
        afternoon = "✓" if info["has_afternoon"] else "✗"
        evening = "✓" if info["has_evening"] else "✗"
        logger.log(f"📅 {date}: {info['count']} events (M:{morning} A:{afternoon} E:{evening})")
    
    logger.log_final_itinerary(events)
    
    return {
        "success": True,
        "events": events,
        "coverage": coverage,
        "scout_stats": {
            "total_links_found": scout_results.get("total_links_found", 0),
            "searches_performed": len(scout_results.get("search_results", []))
        },
        "explorer_stats": {
            "links_analyzed": explorer_results.get("total_analyzed", 0),
            "events_extracted": explorer_results.get("total_events", 0),
            "links_rejected": len(explorer_results.get("rejected", []))
        }
    }


# API Routes
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "model": CONFIG["gemini_model"],
        "architecture": "Scout + Explorer Pipeline"
    }


@app.get("/api/interests")
async def get_interests():
    return {
        "success": True,
        "categories": INTEREST_CATEGORIES,
        "all_tags": get_all_tags()
    }


@app.post("/api/generate-itinerary")
async def generate_itinerary_endpoint(request: GenerateItineraryRequest):
    request_id = str(int(datetime.now().timestamp() * 1000))
    logger = Logger(request_id)
    
    try:
        interest_array = parse_interests(request.interests)
        if not interest_array:
            raise HTTPException(status_code=400, detail="At least one interest is required")
        
        logger.log(f"\n📥 Request ID: {request_id}")
        logger.log(f"📥 City: {request.city}")
        logger.log(f"📥 Interests: {', '.join(interest_array)}")
        logger.log(f"📥 Dates: {request.start_date} to {request.end_date}")
        
        result = await generate_itinerary(
            request.city,
            interest_array,
            request.start_date,
            request.end_date,
            logger
        )
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("message", "Failed to generate itinerary"))
        
        response = {
            "success": True,
            "city": request.city,
            "interests": interest_array,
            "date_range": {
                "start": request.start_date,
                "end": request.end_date
            },
            "itinerary": result["events"],
            "itinerary_by_day": result["coverage"],
            "total_items": len(result["events"]),
            "events": len([e for e in result["events"] if e.get("type") == "event"]),
            "activities": len([e for e in result["events"] if e.get("type") == "activity"]),
            "pipeline_stats": {
                "scout": result["scout_stats"],
                "explorer": result["explorer_stats"]
            },
            "generated_at": datetime.now().isoformat(),
            "request_id": request_id
        }
        
        logger.save_all()
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.log(f"❌ Error: {e}")
        logger.save_all()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-itinerary-stream")
async def generate_itinerary_stream(request: GenerateItineraryRequest):
    """Streaming itinerary generation endpoint (SSE)."""
    request_id = str(int(datetime.now().timestamp() * 1000))
    logger = Logger(request_id)
    
    async def event_generator():
        def send_event(event_type: str, data: Dict[str, Any]):
            return f"data: {json.dumps({'type': event_type, **data})}\n\n"
        
        yield send_event("connected", {"message": "Stream connected", "requestId": request_id})
        
        try:
            interest_array = parse_interests(request.interests)
            if not interest_array:
                yield send_event("error", {"message": "At least one interest is required"})
                return
            
            yield send_event("progress", {
                "phase": "start",
                "message": f"Planning your {request.city} adventure...",
                "detail": f"Looking for {', '.join(interest_array)} experiences"
            })
            
            # Phase 1: Scout
            yield send_event("progress", {
                "phase": "scout",
                "message": "Discovering events and activities...",
                "detail": "Searching multiple sources"
            })
            
            scout_results = await scout_events(
                request.city, interest_array, request.start_date, request.end_date, logger.log
            )
            logger.log_scout_results(scout_results)
            
            if not scout_results.get("all_links"):
                yield send_event("error", {"message": "No events found for your interests"})
                return
            
            yield send_event("progress", {
                "phase": "scout_complete",
                "message": f"Found {scout_results['total_links_found']} potential events!",
                "detail": "Now analyzing each one..."
            })
            
            # Phase 2: Explorer
            yield send_event("progress", {
                "phase": "explorer",
                "message": "Analyzing events...",
                "detail": f"Processing {len(scout_results['all_links'])} sources"
            })
            
            explorer_results = await explore_links(scout_results["all_links"], request.city, logger.log)
            logger.log_explorer_results(explorer_results)
            
            # Phase 3: Organize
            yield send_event("progress", {
                "phase": "organize",
                "message": "Organizing your itinerary...",
                "detail": "Creating your personalized schedule"
            })
            
            events = explorer_results.get("events", [])
            events.sort(key=lambda e: e.get("start_time", "2099-01-01T00:00:00"))
            
            coverage = analyze_event_coverage(events, request.start_date, request.end_date)
            logger.log_final_itinerary(events)
            
            response = {
                "success": True,
                "city": request.city,
                "interests": interest_array,
                "date_range": {"start": request.start_date, "end": request.end_date},
                "itinerary": events,
                "itinerary_by_day": coverage,
                "total_items": len(events),
                "events": len([e for e in events if e.get("type") == "event"]),
                "activities": len([e for e in events if e.get("type") == "activity"]),
                "pipeline_stats": {
                    "scout": {
                        "total_links_found": scout_results.get("total_links_found", 0),
                        "searches_performed": len(scout_results.get("search_results", []))
                    },
                    "explorer": {
                        "links_analyzed": explorer_results.get("total_analyzed", 0),
                        "events_extracted": explorer_results.get("total_events", 0),
                        "links_rejected": len(explorer_results.get("rejected", []))
                    }
                },
                "generated_at": datetime.now().isoformat(),
                "request_id": request_id
            }
            
            yield send_event("complete", {"message": "Itinerary ready!", "data": response})
            logger.save_all()
            
        except Exception as e:
            logger.log(f"❌ Error: {e}")
            logger.save_all()
            yield send_event("error", {"message": str(e)})
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/edit-itinerary")
async def edit_itinerary_endpoint(request: EditItineraryRequest):
    request_id = str(int(datetime.now().timestamp() * 1000))
    
    try:
        print(f"\n📝 Edit Request [{request_id}]")
        print(f"   City: {request.city}")
        print(f"   Edit: \"{request.edit_request}\"")
        print(f"   Activity: {request.current_activity.get('name')}")
        
        edit_result = await process_edit_request(
            edit_request=request.edit_request,
            current_activity=request.current_activity,
            city=request.city or "Unknown City",
            day_date=request.day_date or datetime.now().strftime("%Y-%m-%d"),
            interests=request.interests or []
        )
        
        print(f"✅ Edit processed: {edit_result.get('operation')}")
        print(f"   Summary: {edit_result.get('change_summary')}")
        
        return {
            "success": True,
            **edit_result,
            "request_id": request_id,
            "processed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"❌ Edit Error [{request_id}]: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Main entry point
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 Itinerary API Server Running")
    print("   Architecture: Scout + Explorer Pipeline")
    print("=" * 60)
    print(f"📡 Server: http://localhost:{CONFIG['port']}")
    print(f"🤖 Model: {CONFIG['gemini_model']}")
    print("🔧 Endpoints:")
    print("   GET  /health")
    print("   GET  /api/interests")
    print("   POST /api/generate-itinerary")
    print("   POST /api/generate-itinerary-stream")
    print("   POST /api/edit-itinerary")
    print("=" * 60)
    print("\n📋 Pipeline Flow:")
    print("   1. Scout  → Search for event links per interest/day")
    print("   2. Explorer → Analyze links, extract event details")
    print("   3. Organize → Sort and group events by day")
    print("=" * 60)
    print("\n✅ Ready to generate itineraries!\n")
    
    uvicorn.run(app, host="0.0.0.0", port=CONFIG["port"])
