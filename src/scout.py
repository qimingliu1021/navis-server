"""
Scout Module - Event Link Discovery (OPTIMIZED)
Uses parallel searches for each interest to dramatically reduce search time
"""

import os
import json
import asyncio
import re
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional

from google import genai

CONFIG = {
    "google_api_key": os.getenv("GOOGLE_API_KEY"),
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    "links_per_search": 15,
    "max_concurrent_searches": 4,
}

# Gemini client (lazy init)
_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Get or create Gemini client."""
    global _client
    if _client is None:
        if not CONFIG["google_api_key"]:
            raise ValueError("GOOGLE_API_KEY is required for Scout")
        _client = genai.Client(api_key=CONFIG["google_api_key"])
    return _client


def build_search_prompt(interest: str, city: str, start_date: str, end_date: str) -> str:
    """Build the prompt for Gemini to search and extract links."""
    start_obj = datetime.fromisoformat(start_date)
    end_obj = datetime.fromisoformat(end_date)
    
    formatted_start = start_obj.strftime("%B %d, %Y")
    formatted_end = end_obj.strftime("%B %d, %Y")
    
    return f"""You are an Event Link Scout. Search the web and find URLs to event pages.

## TASK:
Find "{interest}" events in {city} between {formatted_start} and {formatted_end}.

## SEARCH STRATEGY:
Search these platforms for "{interest}" events in {city}:
- Eventbrite
- Meetup  
- Luma (lu.ma)
- Local venue calendars
- Facebook Events

## REQUIREMENTS:
1. Find up to {CONFIG['links_per_search']} unique event links
2. Only actual event pages (not homepages or search results)
3. Events must be within the date range
4. Include snippet showing why link is relevant

## OUTPUT FORMAT (JSON only):
{{
  "interest": "{interest}",
  "city": "{city}",
  "date_range": "{start_date} to {end_date}",
  "links": [
    {{
      "url": "https://event-page-url.com",
      "title": "Event title",
      "snippet": "Brief description",
      "platform": "Eventbrite/Meetup/Luma/Other",
      "event_date": "YYYY-MM-DD if known"
    }}
  ],
  "total_found": 10
}}

CRITICAL: Output ONLY valid JSON. Start with {{ end with }}"""


def extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from response."""
    if not text:
        raise ValueError("Empty response text")
    
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try code block
    code_match = re.search(r'```json\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if code_match:
        try:
            return json.loads(code_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON object
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    raise ValueError("Could not extract JSON from Scout response")


async def search_for_interest(
    interest: str,
    city: str,
    start_date: str,
    end_date: str,
    logger: Callable[[str], None]
) -> Dict[str, Any]:
    """Search for event links for a single interest across the date range."""
    client = get_client()
    prompt = build_search_prompt(interest, city, start_date, end_date)
    
    logger(f'🔍 Scout: Searching "{interest}" events in {city}')
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=CONFIG["gemini_model"],
            contents=prompt,
            config={
                "tools": [{"google_search": {}}],
                "temperature": 0.2,
                "max_output_tokens": 4096,
            }
        )
        
        response_text = response.text
        result = extract_json(response_text)
        
        links_count = len(result.get("links", []))
        logger(f'✅ Scout: Found {links_count} links for "{interest}"')
        
        return {
            "success": True,
            "interest": interest,
            "city": city,
            "start_date": start_date,
            "end_date": end_date,
            "links": result.get("links", [])
        }
    except Exception as e:
        logger(f'❌ Scout: Error searching "{interest}": {e}')
        return {
            "success": False,
            "interest": interest,
            "city": city,
            "links": [],
            "error": str(e)
        }


async def run_with_concurrency(tasks: List, limit: int) -> List:
    """Run async tasks with concurrency limit."""
    semaphore = asyncio.Semaphore(limit)
    
    async def run_task(task):
        async with semaphore:
            return await task
    
    return await asyncio.gather(*[run_task(t) for t in tasks], return_exceptions=True)


async def scout_events(
    city: str,
    interests: List[str],
    start_date: str,
    end_date: str,
    logger: Callable[[str], None] = print
) -> Dict[str, Any]:
    """
    Main Scout function - PARALLEL searches for all interests.
    
    Args:
        city: The city to search
        interests: Array of interests
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        logger: Optional logging function
    
    Returns:
        All discovered links
    """
    logger("\n🔭 Scout: Starting PARALLEL event discovery")
    logger(f"📍 City: {city}")
    logger(f"🎯 Interests: {', '.join(interests)}")
    logger(f"📅 Dates: {start_date} to {end_date}")
    logger(f"⚡ Running {len(interests)} searches in parallel (max {CONFIG['max_concurrent_searches']} concurrent)")
    
    all_results = {
        "city": city,
        "interests": interests,
        "start_date": start_date,
        "end_date": end_date,
        "search_results": [],
        "all_links": [],
        "total_links_found": 0
    }
    
    # Create tasks for parallel execution
    tasks = [
        search_for_interest(interest, city, start_date, end_date, logger)
        for interest in interests
    ]
    
    # Execute all searches in parallel with concurrency limit
    import time
    start_time = time.time()
    results = await run_with_concurrency(tasks, CONFIG["max_concurrent_searches"])
    duration = round(time.time() - start_time, 1)
    
    logger(f"⏱️ All searches completed in {duration}s")
    
    # Process results
    for result in results:
        all_results["search_results"].append(result)
        if result.get("links"):
            for link in result["links"]:
                all_results["all_links"].append({
                    **link,
                    "interest": result["interest"],
                    "date": link.get("event_date", start_date),
                    "searched_at": datetime.now().isoformat()
                })
    
    # Deduplicate links by URL
    unique_links = []
    seen_urls = set()
    
    for link in all_results["all_links"]:
        if link["url"] not in seen_urls:
            seen_urls.add(link["url"])
            unique_links.append(link)
    
    all_results["all_links"] = unique_links
    all_results["total_links_found"] = len(unique_links)
    
    logger(f"\n✅ Scout: Completed! Found {all_results['total_links_found']} unique links in {duration}s")
    
    return all_results
