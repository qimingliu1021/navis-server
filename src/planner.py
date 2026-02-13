"""
Planner Module - Event Organization Utilities
Provides helper functions for sorting, grouping, and optimizing itineraries
"""

from typing import List, Dict, Any, Optional
from datetime import datetime


def sort_by_time(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort events chronologically by start_time."""
    return sorted(
        events,
        key=lambda e: datetime.fromisoformat(e.get("start_time", "2099-01-01T00:00:00"))
    )


def group_by_date(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by date."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    
    for event in events:
        if event.get("start_time"):
            date = event["start_time"].split("T")[0]
            if date not in grouped:
                grouped[date] = []
            grouped[date].append(event)
    
    return grouped


def group_by_category(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by interest/category."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    
    for event in events:
        category = event.get("category", "other")
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(event)
    
    return grouped


def remove_duplicates(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate events based on name and start_time."""
    seen = set()
    unique = []
    
    for event in events:
        key = f"{event.get('name')}-{event.get('start_time')}"
        if key not in seen:
            seen.add(key)
            unique.append(event)
    
    return unique


def filter_by_date_range(
    events: List[Dict[str, Any]], 
    start_date: str, 
    end_date: str
) -> List[Dict[str, Any]]:
    """Filter events by date range."""
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(f"{end_date}T23:59:59")
    
    return [
        event for event in events
        if event.get("start_time") and 
           start <= datetime.fromisoformat(event["start_time"]) <= end
    ]


def find_schedule_gaps(day_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze schedule gaps for a single day."""
    if len(day_events) < 2:
        return []
    
    gaps = []
    sorted_events = sort_by_time(day_events)
    
    for i in range(len(sorted_events) - 1):
        current_end = datetime.fromisoformat(sorted_events[i]["end_time"])
        next_start = datetime.fromisoformat(sorted_events[i + 1]["start_time"])
        gap_minutes = (next_start - current_end).total_seconds() / 60
        
        if gap_minutes > 60:  # Gap > 1 hour
            gaps.append({
                "after_event": sorted_events[i]["name"],
                "before_event": sorted_events[i + 1]["name"],
                "start": sorted_events[i]["end_time"],
                "end": sorted_events[i + 1]["start_time"],
                "duration_minutes": gap_minutes
            })
    
    return gaps


def get_time_distribution(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Get time-of-day distribution for events."""
    distribution = {
        "morning": [],    # 6am - 12pm
        "afternoon": [],  # 12pm - 5pm
        "evening": [],    # 5pm - 9pm
        "night": []       # 9pm - 6am
    }
    
    for event in events:
        if not event.get("start_time"):
            continue
        
        hour = int(event["start_time"].split("T")[1].split(":")[0])
        
        if 6 <= hour < 12:
            distribution["morning"].append(event)
        elif 12 <= hour < 17:
            distribution["afternoon"].append(event)
        elif 17 <= hour < 21:
            distribution["evening"].append(event)
        else:
            distribution["night"].append(event)
    
    return distribution


def calculate_total_duration(events: List[Dict[str, Any]]) -> int:
    """Calculate total duration of events in minutes."""
    return sum(event.get("duration_minutes", 0) for event in events)


def format_itinerary(events: List[Dict[str, Any]]) -> str:
    """Format itinerary for display."""
    grouped = group_by_date(events)
    output = ""
    
    for date in sorted(grouped.keys()):
        day_events = grouped[date]
        date_obj = datetime.fromisoformat(date)
        formatted = date_obj.strftime("%A, %B %d")
        
        output += f"\n📅 {formatted}\n"
        output += "─" * 40 + "\n"
        
        for event in sort_by_time(day_events):
            time = event["start_time"].split("T")[1][:5]
            output += f"  {time} - {event.get('name', 'TBD')}\n"
            venue = event.get("location", {}).get("venue", "TBD")
            output += f"         📍 {venue}\n"
    
    return output


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
