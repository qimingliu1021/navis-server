"""
Edit Itinerary Module - AI-powered itinerary editing
Handles individual activity modifications using Gemini AI
"""

import os
import json
import re
from typing import Dict, Any, List, Optional

from google import genai

CONFIG = {
    "google_api_key": os.getenv("GOOGLE_API_KEY"),
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
}

# Gemini client (lazy init)
_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    """Get or create Gemini client."""
    global _client
    if _client is None:
        if not CONFIG["google_api_key"]:
            raise ValueError("GOOGLE_API_KEY is required for edit operations")
        _client = genai.Client(api_key=CONFIG["google_api_key"])
    return _client


async def process_edit_request(
    edit_request: str,
    current_activity: Dict[str, Any],
    city: str,
    day_date: str,
    interests: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Edit a single activity using AI.
    
    Args:
        edit_request: User's edit request
        current_activity: Current activity to edit
        city: City name
        day_date: Date of the activity
        interests: User interests
    
    Returns:
        Edit result
    """
    import asyncio
    
    system_prompt = f"""You are an itinerary editing assistant. Your job is to help users modify their travel plans.

You MUST respond with ONLY valid JSON (no markdown, no backticks, no explanation).

Based on the user's request, determine the appropriate operation and provide the result.

Operations:
1. "replace" - Replace the current activity with a new one (user wants something different)
2. "delete" - Remove the activity (user doesn't want it)
3. "update_time" - Only change the timing
4. "update_description" - Only change the description
5. "add" - Add a new activity (user wants to add something nearby/after)

For "replace" or "add" operations, you must provide realistic details:
- Real place names that exist in {city}
- Realistic coordinates (latitude/longitude for {city})
- Appropriate timing based on the activity type
- Detailed description

Response format:
{{
  "operation": "replace|delete|update_time|update_description|add",
  "updated_activity": {{
    "name": "Place Name",
    "location": "Full address",
    "coordinates": {{ "lat": number, "lng": number }},
    "start_time": "ISO datetime",
    "end_time": "ISO datetime",
    "description": "Description of the place",
    "type": "activity|restaurant|attraction",
    "tags": ["tag1", "tag2"]
  }},
  "new_activity": {{ ... }},  // Only for "add" operation
  "change_summary": "Brief description of what changed"
}}

For "delete" operation, only include:
{{
  "operation": "delete",
  "change_summary": "Removed X from itinerary"
}}

For "update_time" operation:
{{
  "operation": "update_time",
  "updated_activity": {{
    "start_time": "new ISO datetime",
    "end_time": "new ISO datetime"
  }},
  "change_summary": "Changed time to X"
}}"""

    interests_str = ", ".join(interests) if interests else "general"
    
    user_prompt = f"""City: {city}
Date: {day_date}
User interests: {interests_str}

Current activity:
{json.dumps(current_activity, indent=2)}

User's edit request: "{edit_request}"

Provide the appropriate edit response as JSON."""

    try:
        client = get_client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=CONFIG["gemini_model"],
            contents=system_prompt + "\n\n" + user_prompt,
            config={
                "temperature": 0.3,
                "max_output_tokens": 2048,
            }
        )
        
        text = response.text
        if not text:
            raise ValueError("AI model returned empty response. Please try again.")
        
        # Parse JSON from response
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract from markdown code block
            code_match = re.search(r'```json\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
            if code_match:
                try:
                    parsed = json.loads(code_match.group(1).strip())
                except json.JSONDecodeError:
                    parsed = None
            else:
                parsed = None
            
            # Try to extract JSON if model added extra text
            if not parsed:
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    try:
                        parsed = json.loads(text[start:end + 1])
                    except json.JSONDecodeError:
                        raise ValueError(f"Model did not return valid JSON: {text[:200]}")
                else:
                    raise ValueError(f"No JSON found in response: {text[:200]}")
        
        return parsed
        
    except Exception as e:
        print(f"AI processing error: {e}")
        raise
