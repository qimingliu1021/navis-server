"""
Scout Module - Event Link Discovery
Uses Tavily API for web search and Gemini for query construction + verification.
Parallel searches across multiple interests with link validation.
"""

import os
import json
import asyncio
import re
import time
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional

from google import genai
from tavily import AsyncTavilyClient

CONFIG = {
    "google_api_key": os.getenv("GOOGLE_API_KEY"),
    "tavily_api_key": os.getenv("TAVILY_API_KEY"),
    "gemini_flash_model": os.getenv("GEMINI_FLASH_MODEL", "gemini-2.0-flash"),
    "links_per_search": 10,          # Decreased from 15 → 10
    "max_concurrent_searches": 4,
}

# Clients (lazy init)
_gemini_client: Optional[genai.Client] = None
_tavily_client: Optional[AsyncTavilyClient] = None


def get_gemini_client() -> genai.Client:
    """Get or create Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        if not CONFIG["google_api_key"]:
            raise ValueError("GOOGLE_API_KEY is required for Scout")
        _gemini_client = genai.Client(api_key=CONFIG["google_api_key"])
    return _gemini_client


def get_tavily_client() -> AsyncTavilyClient:
    """Get or create async Tavily client."""
    global _tavily_client
    if _tavily_client is None:
        if not CONFIG["tavily_api_key"]:
            raise ValueError("TAVILY_API_KEY is required for Scout")
        _tavily_client = AsyncTavilyClient(api_key=CONFIG["tavily_api_key"])
    return _tavily_client


# ---------------------------------------------------------------------------
# Phase 1: Use Gemini to generate smart search queries per interest
# ---------------------------------------------------------------------------

QUERY_GENERATION_PROMPT = """Generate 1 highly targeted web search query to find "{interest}" events in {city} between {formatted_start} and {formatted_end}.

Rules:
- Include city name and month/year info
- Target event listing platforms (Eventbrite, Meetup, etc.)
- Be specific enough to find real event pages

Return JSON with a single key "query" containing the query string."""


def extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from Gemini response."""
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

    raise ValueError("Could not extract JSON from response")


async def generate_search_query(
    interest: str,
    city: str,
    start_date: str,
    end_date: str,
    logger: Callable[[str], None]
) -> str:
    """Use Gemini to generate a single optimized search query for an interest."""
    client = get_gemini_client()

    start_obj = datetime.fromisoformat(start_date)
    end_obj = datetime.fromisoformat(end_date)
    formatted_start = start_obj.strftime("%B %d, %Y")
    formatted_end = end_obj.strftime("%B %d, %Y")

    prompt = QUERY_GENERATION_PROMPT.format(
        interest=interest,
        city=city,
        formatted_start=formatted_start,
        formatted_end=formatted_end,
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=CONFIG["gemini_flash_model"],
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.3,
                "max_output_tokens": 512,
            },
        )
        result = extract_json(response.text)
        query = result.get("query", "")
        logger(f'🧠 Gemini: Generated query for "{interest}": "{query}"')
        return query
    except Exception as e:
        logger(f'⚠️ Gemini query gen failed for "{interest}": {e}')
        # Fallback: construct query manually
        month_year = datetime.fromisoformat(start_date).strftime("%B %Y")
        fallback = f"{interest} events in {city} {month_year} Eventbrite Meetup"
        logger(f'📝 Using fallback query for "{interest}": "{fallback}"')
        return fallback


# ---------------------------------------------------------------------------
# Phase 2: Execute Tavily searches in parallel
# ---------------------------------------------------------------------------

EVENT_DOMAINS = [
    "eventbrite.com",
    "meetup.com",
    "lu.ma",
    "facebook.com/events",
    "allevents.in",
]

REJECT_DOMAINS = [
    "youtube.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "yelp.com",
    "tripadvisor.com",
]


async def tavily_search(
    query: str,
    max_results: int,
    logger: Callable[[str], None]
) -> List[Dict[str, Any]]:
    """Execute a single Tavily search and return results."""
    client = get_tavily_client()

    try:
        response = await client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            exclude_domains=REJECT_DOMAINS,
        )
        results = response.get("results", [])
        logger(f"🔍 Tavily: \"{query[:60]}...\" → {len(results)} results")
        return results
    except Exception as e:
        logger(f"❌ Tavily search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Phase 3: Use Gemini to verify / filter links
# ---------------------------------------------------------------------------

VERIFY_PROMPT = """Filter these search results for "{interest}" events in {city} ({start_date} to {end_date}).

KEEP links that are:
- Specific event pages (Eventbrite, Meetup, Luma, venue event pages)
- Event listing pages that contain relevant events
- Pages about specific happenings, workshops, meetups, conferences

REJECT only:
- Generic "top 10" listicle articles
- Pure venue homepages with no event info
- Clearly wrong city or completely wrong date range

When in doubt, KEEP the link. Be generous.

Search results:
{results_text}

Return JSON with "verified_links" array (each with url, title, snippet, platform, event_date, relevance) and "rejected_count"."""


async def verify_links(
    results: List[Dict[str, Any]],
    interest: str,
    city: str,
    start_date: str,
    end_date: str,
    logger: Callable[[str], None]
) -> List[Dict[str, Any]]:
    """Use Gemini to verify and filter search results into valid event links."""
    if not results:
        return []

    client = get_gemini_client()

    # Format results for Gemini
    results_text = "\n---\n".join([
        f"[{i+1}] Title: {r.get('title', 'N/A')}\n"
        f"    URL: {r.get('url', 'N/A')}\n"
        f"    Content: {r.get('content', 'N/A')[:300]}"
        for i, r in enumerate(results)
    ])

    prompt = VERIFY_PROMPT.format(
        city=city,
        start_date=start_date,
        end_date=end_date,
        interest=interest,
        results_text=results_text,
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=CONFIG["gemini_flash_model"],
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": 4096,
            },
        )
        result = extract_json(response.text)
        verified = result.get("verified_links", [])
        rejected = result.get("rejected_count", 0)
        logger(f'✅ Verified: {len(verified)} links kept, {rejected} rejected for "{interest}"')
        return verified
    except Exception as e:
        logger(f'⚠️ Verification failed for "{interest}": {e}')
        # Fallback: return raw results as-is with basic filtering
        return [
            {
                "url": r["url"],
                "title": r.get("title", "Unknown"),
                "snippet": r.get("content", "")[:200],
                "platform": _guess_platform(r.get("url", "")),
                "event_date": "unknown",
                "relevance": "medium",
            }
            for r in results
            if not any(d in r.get("url", "") for d in REJECT_DOMAINS)
        ]


def _guess_platform(url: str) -> str:
    """Guess the platform from a URL."""
    if "eventbrite" in url:
        return "Eventbrite"
    if "meetup" in url:
        return "Meetup"
    if "lu.ma" in url:
        return "Luma"
    if "facebook.com" in url:
        return "Facebook"
    if "allevents.in" in url:
        return "AllEvents"
    return "Other"


# ---------------------------------------------------------------------------
# Main pipeline: per-interest search
# ---------------------------------------------------------------------------

async def search_for_interest(
    interest: str,
    city: str,
    start_date: str,
    end_date: str,
    logger: Callable[[str], None]
) -> Dict[str, Any]:
    """Full pipeline for a single interest: generate query → search → verify."""
    logger(f'🎯 Scout: Starting pipeline for "{interest}"')

    # Step 1: Generate a single search query with Gemini
    query = await generate_search_query(interest, city, start_date, end_date, logger)

    # Step 2: Run Tavily search
    max_results = CONFIG["links_per_search"]
    results = await tavily_search(query, max_results, logger)

    # Deduplicate by URL
    all_raw = []
    seen_urls = set()
    for r in results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_raw.append(r)

    logger(f'📊 Raw results for "{interest}": {len(all_raw)} unique URLs')

    if not all_raw:
        return {
            "success": False,
            "interest": interest,
            "city": city,
            "links": [],
            "error": "No search results found",
        }

    # Step 3: Verify and filter with Gemini
    verified_links = await verify_links(all_raw, interest, city, start_date, end_date, logger)

    return {
        "success": True,
        "interest": interest,
        "city": city,
        "start_date": start_date,
        "end_date": end_date,
        "links": verified_links,
    }


# ---------------------------------------------------------------------------
# Concurrency helper
# ---------------------------------------------------------------------------

async def run_with_concurrency(tasks: List, limit: int) -> List:
    """Run async tasks with concurrency limit."""
    semaphore = asyncio.Semaphore(limit)

    async def run_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*[run_task(t) for t in tasks], return_exceptions=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def scout_events(
    city: str,
    interests: List[str],
    start_date: str,
    end_date: str,
    logger: Callable[[str], None] = print
) -> Dict[str, Any]:
    """
    Main Scout function — parallel searches across all interests.

    Pipeline per interest:
      1. Gemini generates optimized search queries
      2. Tavily executes web searches
      3. Gemini verifies/filters results into valid event links

    Args:
        city: The city to search
        interests: List of interest keywords
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        logger: Logging function

    Returns:
        Dict with all discovered and verified links
    """
    logger("\n🔭 Scout: Starting event discovery (Tavily + Gemini)")
    logger(f"📍 City: {city}")
    logger(f"🎯 Interests: {', '.join(interests)}")
    logger(f"📅 Dates: {start_date} to {end_date}")
    logger(f"⚡ Running {len(interests)} interest pipelines in parallel "
           f"(max {CONFIG['max_concurrent_searches']} concurrent)")

    all_results: Dict[str, Any] = {
        "city": city,
        "interests": interests,
        "start_date": start_date,
        "end_date": end_date,
        "search_results": [],
        "all_links": [],
        "total_links_found": 0,
    }

    # Create per-interest pipeline tasks
    tasks = [
        search_for_interest(interest, city, start_date, end_date, logger)
        for interest in interests
    ]

    start_time = time.time()
    results = await run_with_concurrency(tasks, CONFIG["max_concurrent_searches"])
    duration = round(time.time() - start_time, 1)

    logger(f"⏱️  All interest pipelines completed in {duration}s")

    # Collect results
    for result in results:
        if isinstance(result, Exception):
            logger(f"⚠️ An interest pipeline failed: {result}")
            continue

        all_results["search_results"].append(result)
        if result.get("links"):
            for link in result["links"]:
                all_results["all_links"].append({
                    **link,
                    "interest": result["interest"],
                    "date": link.get("event_date", start_date),
                    "searched_at": datetime.now().isoformat(),
                })

    # Deduplicate by URL
    unique_links = []
    seen_urls: set = set()
    for link in all_results["all_links"]:
        url = link.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_links.append(link)

    all_results["all_links"] = unique_links
    all_results["total_links_found"] = len(unique_links)

    logger(f"\n✅ Scout: Completed! Found {all_results['total_links_found']} "
           f"verified links in {duration}s")

    return all_results
