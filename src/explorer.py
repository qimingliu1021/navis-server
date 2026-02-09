"""
Explorer Module - Event Link Analysis (OPTIMIZED)
Analyzes links from Scout using parallel batch processing
"""

import os
import json
import asyncio
import re
from typing import List, Dict, Any, Callable, Optional

from google import genai

CONFIG = {
    "google_api_key": os.getenv("GOOGLE_API_KEY"),
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    "batch_size": 5,
    "max_concurrent_batches": 3,
}

# Gemini client (lazy init)
_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Get or create Gemini client."""
    global _client
    if _client is None:
        if not CONFIG["google_api_key"]:
            raise ValueError("GOOGLE_API_KEY is required for Explorer")
        _client = genai.Client(api_key=CONFIG["google_api_key"])
    return _client


def build_analysis_prompt(links: List[Dict[str, Any]], city: str) -> str:
    """Build prompt for analyzing a batch of links."""
    links_info = "\n---".join([
        f"""
[Link {i + 1}]
URL: {link.get('url')}
Title: {link.get('title', 'Unknown')}
Snippet: {link.get('snippet', 'No snippet')}
Interest: {link.get('interest')}
Platform: {link.get('platform', 'Unknown')}"""
        for i, link in enumerate(links)
    ])
    
    return f"""You are an Expert Event Analyzer. Analyze these event links and extract details.

## LINKS TO ANALYZE:
{links_info}

## CRITERIA FOR VALID EVENTS:
1. Must have a specific start time (not just "Open 10am-6pm")
2. Must have a human host/organizer
3. Must be IN-PERSON in {city} (NO online/virtual/zoom events)
4. Must be a real event (meetup, workshop, class, talk, etc.)

## REJECT:
- General admission / timed entry slots
- Self-guided tours
- Online/Virtual/Zoom events
- Events without physical address in {city}

## EXTRACT FOR VALID EVENTS:
- name, type, category
- location (venue, address, city)
- coordinates (lat/lng)
- start_time, end_time (ISO 8601)
- description, pricing, tags

## OUTPUT FORMAT (JSON only):
{{
  "analyzed_links": {len(links)},
  "valid_events": [
    {{
      "name": "Event Name",
      "type": "event",
      "category": "meetup/workshop/networking/tour/class/talk/other",
      "location": {{ "venue": "Name", "address": "Full address", "city": "{city}" }},
      "coordinates": {{"lat": 0.0, "lng": 0.0}},
      "start_time": "2026-01-03T18:00:00",
      "end_time": "2026-01-03T20:00:00",
      "duration_minutes": 120,
      "description": "Brief description",
      "source": {{ "platform": "Eventbrite", "url": "exact-url" }},
      "pricing": {{ "is_free": true, "price": "Free", "currency": "USD" }},
      "tags": ["tag1", "tag2"]
    }}
  ],
  "rejected_links": [
    {{ "url": "https://...", "reason": "Online event" }}
  ]
}}

Output ONLY valid JSON. Start with {{ end with }}"""


def is_online_event(event: Dict[str, Any]) -> bool:
    """Check if an event is online/virtual."""
    online_keywords = [
        "online", "virtual", "remote", "zoom", "webinar",
        "livestream", "google meet", "teams", "webex",
        "discord", "streaming"
    ]
    
    fields_to_check = [
        event.get("location", {}).get("venue", ""),
        event.get("location", {}).get("address", ""),
        event.get("name", ""),
        event.get("description", "")
    ]
    fields_to_check = [f.lower() for f in fields_to_check if f]
    
    for field in fields_to_check:
        for keyword in online_keywords:
            if keyword in field:
                return True
    
    location = event.get("location", {})
    if location:
        venue = (location.get("venue") or "").lower()
        address = (location.get("address") or "").lower()
        if not address or address in ["tbd", "online", "virtual"]:
            if not venue or venue in ["online", "virtual", "tbd"]:
                return True
    
    return False


def extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from response."""
    if not text:
        raise ValueError("Empty response text")
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    code_match = re.search(r'```json\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if code_match:
        try:
            return json.loads(code_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    raise ValueError("Could not extract JSON from Explorer response")


async def analyze_batch(
    links: List[Dict[str, Any]],
    city: str,
    batch_num: int,
    total_batches: int,
    logger: Callable[[str], None]
) -> Dict[str, Any]:
    """Analyze a batch of links."""
    client = get_client()
    prompt = build_analysis_prompt(links, city)
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=CONFIG["gemini_model"],
            contents=prompt,
            config={
                "tools": [{"google_search": {}}],
                "temperature": 0.1,
                "max_output_tokens": 8192,
            }
        )
        
        response_text = response.text
        result = extract_json(response_text)
        
        events_count = len(result.get("valid_events", []))
        logger(f"✅ Batch {batch_num}/{total_batches}: Found {events_count} valid events")
        
        return {
            "success": True,
            "events": result.get("valid_events", []),
            "rejected": result.get("rejected_links", []),
            "analyzed": result.get("analyzed_links", len(links))
        }
    except Exception as e:
        logger(f"❌ Batch {batch_num}/{total_batches}: Failed - {e}")
        return {
            "success": False,
            "events": [],
            "rejected": [{"url": link["url"], "reason": str(e)} for link in links],
            "error": str(e)
        }


async def run_with_concurrency(tasks: List, limit: int) -> List:
    """Run async tasks with concurrency limit."""
    semaphore = asyncio.Semaphore(limit)
    
    async def run_task(task):
        async with semaphore:
            return await task
    
    return await asyncio.gather(*[run_task(t) for t in tasks])


async def explore_links(
    links: List[Dict[str, Any]],
    city: str,
    logger: Callable[[str], None] = print
) -> Dict[str, Any]:
    """Main Explorer function - PARALLEL batch processing."""
    logger("\n🔬 Explorer: Starting PARALLEL link analysis")
    logger(f"📊 Links to analyze: {len(links)}")
    
    if not links:
        logger("⚠️ Explorer: No links to analyze")
        return {
            "success": True,
            "events": [],
            "total_analyzed": 0,
            "total_events": 0,
            "rejected": []
        }
    
    # Create batches
    batches = []
    for i in range(0, len(links), CONFIG["batch_size"]):
        batches.append(links[i:i + CONFIG["batch_size"]])
    
    logger(f"📦 Explorer: Processing {len(batches)} batches ({CONFIG['max_concurrent_batches']} concurrent)")
    
    # Create tasks for parallel execution
    tasks = [
        analyze_batch(batch, city, i + 1, len(batches), logger)
        for i, batch in enumerate(batches)
    ]
    
    # Execute batches in parallel with concurrency limit
    import time
    start_time = time.time()
    results = await run_with_concurrency(tasks, CONFIG["max_concurrent_batches"])
    duration = round(time.time() - start_time, 1)
    
    logger(f"⏱️ All batches completed in {duration}s")
    
    # Collect results
    all_events = []
    all_rejected = []
    total_analyzed = 0
    
    for result in results:
        if result["success"]:
            all_events.extend(result["events"])
            all_rejected.extend(result["rejected"])
            total_analyzed += result["analyzed"]
        else:
            all_rejected.extend(result["rejected"])
    
    # Deduplicate events
    unique_events = []
    seen = set()
    
    for event in all_events:
        key = f"{event.get('name')}-{event.get('start_time')}"
        if key not in seen:
            seen.add(key)
            unique_events.append(event)
    
    # Sort by start_time
    unique_events.sort(
        key=lambda e: e.get("start_time", "2099-01-01T00:00:00")
    )
    
    # Filter out online events
    in_person_events = []
    for event in unique_events:
        if is_online_event(event):
            logger(f"🚫 Filtered online event: {event.get('name')}")
        else:
            in_person_events.append(event)
    
    logger(f"\n✅ Explorer: Completed in {duration}s!")
    logger(f"📊 Total links analyzed: {total_analyzed}")
    logger(f"🎯 Valid in-person events: {len(in_person_events)}")
    logger(f"❌ Rejected: {len(all_rejected)}")
    
    return {
        "success": True,
        "events": in_person_events,
        "total_analyzed": total_analyzed,
        "total_events": len(in_person_events),
        "rejected": all_rejected
    }


async def analyze_link(
    link: Dict[str, Any],
    city: str,
    logger: Callable[[str], None] = print
) -> Dict[str, Any]:
    """Analyze a single link."""
    return await analyze_batch([link], city, 1, 1, logger)
