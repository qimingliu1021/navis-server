from typing import TypedDict, List, Dict, Any, Optional
from typing_extensions import Annotated
import operator

class ItineraryState(TypedDict):
    # Input
    city: str
    interests: List[str]
    start_date: str
    end_date: str
    
    # Internal State
    scout_links: List[Dict[str, Any]]
    explorer_events: List[Dict[str, Any]]
    
    # Output
    itinerary: List[Dict[str, Any]]
    coverage: Dict[str, Any]
    
    # Metadata/Logs
    logs: Annotated[List[str], operator.add]
