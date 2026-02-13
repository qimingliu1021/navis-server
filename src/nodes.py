import json
from datetime import datetime
from typing import Dict, Any

from state import ItineraryState
from scout import scout_events
from explorer import explore_links
from planner import analyze_event_coverage, sort_by_time

async def scout_node(state: ItineraryState) -> Dict[str, Any]:
    """
    Scout Node: Finds event links based on interests.
    """
    city = state["city"]
    interests = state["interests"]
    start_date = state["start_date"]
    end_date = state["end_date"]
    
    # Simple logger that prints to stdout (LangGraph captures stdout usually)
    # in a real app we might want to append to state["logs"] but that can get large.
    def log_func(msg: str):
        print(f"[Scout] {msg}")
    
    log_func(f"Starting scout for {city} with interests: {interests}")
    
    results = await scout_events(city, interests, start_date, end_date, log_func)
    
    return {
        "scout_links": results.get("all_links", []),
        "logs": [f"Scout found {results.get('total_links_found', 0)} links"]
    }


async def explorer_node(state: ItineraryState) -> Dict[str, Any]:
    """
    Explorer Node: Analyzes links to find valid events.
    """
    links = state.get("scout_links", [])
    city = state["city"]
    
    def log_func(msg: str):
        print(f"[Explorer] {msg}")
        
    log_func(f"Starting explorer with {len(links)} links")
    
    results = await explore_links(links, city, log_func)
    
    return {
        "explorer_events": results.get("events", []),
        "logs": [f"Explorer found {results.get('total_events', 0)} valid events"]
    }


async def planner_node(state: ItineraryState) -> Dict[str, Any]:
    """
    Planner Node: Organizes events and calculates coverage.
    """
    events = state.get("explorer_events", [])
    start_date = state["start_date"]
    end_date = state["end_date"]
    
    # Sort events
    sorted_events = sort_by_time(events)
    
    # Analyze coverage
    coverage = analyze_event_coverage(sorted_events, start_date, end_date)
    
    return {
        "itinerary": sorted_events,
        "coverage": coverage,
        "logs": ["Planner organized events and calculated coverage"]
    }
