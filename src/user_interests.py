"""
User Interests Configuration
Backend module for interest categories and tags used in itinerary generation
"""

from typing import List, Set, Dict

# Interest categories with their associated tags
INTEREST_CATEGORIES = [
    {
        "name": "Outdoor",
        "tags": [
            "Hiking", "Camping", "Road Trips", "Beach", "Mountains",
            "National Parks", "Adventure Travel", "Backpacking"
        ]
    },
    {
        "name": "Social Activities",
        "tags": [
            "Networking", "Meetups", "Social Events", "Parties",
            "Happy Hour", "Clubbing", "Bars", "Dancing"
        ]
    },
    {
        "name": "Hobbies and Passion",
        "tags": [
            "Photography", "Reading", "Writing", "Crafts",
            "DIY", "Vintage Fashion", "Sneakers", "Collecting"
        ]
    },
    {
        "name": "Sports and Fitness",
        "tags": [
            "Gym", "Running", "Yoga", "Swimming", "Cycling",
            "Basketball", "Soccer", "Tennis", "Martial Arts"
        ]
    },
    {
        "name": "Health and Wellbeing",
        "tags": [
            "Meditation", "Wellness", "Spa", "Mental Health",
            "Nutrition", "Mindfulness", "Self-care"
        ]
    },
    {
        "name": "Technology",
        "tags": [
            "Coding", "AI", "Startups", "Tech Meetups",
            "Hackathons", "Gaming Tech", "VR", "Crypto"
        ]
    },
    {
        "name": "Art and Culture",
        "tags": [
            "Museums", "Art Galleries", "Theater", "Opera",
            "Ballet", "Film", "Concerts", "Live Music"
        ]
    },
    {
        "name": "Games",
        "tags": [
            "Video Games", "Board Games", "E-Sports", "Gaming",
            "Tabletop RPG", "Card Games", "Arcade"
        ]
    },
    {
        "name": "Career and Business",
        "tags": [
            "Networking", "Conferences", "Workshops",
            "Professional Development", "Entrepreneurship", "Leadership"
        ]
    },
    {
        "name": "Science and Education",
        "tags": [
            "Lectures", "Workshops", "Book Clubs", "Learning",
            "Research", "STEM", "History", "Language Exchange"
        ]
    }
]


def get_all_tags() -> List[str]:
    """Get all available tags as a flat array."""
    all_tags: Set[str] = set()
    for category in INTEREST_CATEGORIES:
        for tag in category["tags"]:
            all_tags.add(tag)
    return sorted(list(all_tags))


def get_category_names() -> List[str]:
    """Get category names."""
    return [cat["name"] for cat in INTEREST_CATEGORIES]


def find_categories_for_interests(interests: List[str]) -> List[str]:
    """Find which categories contain given interests."""
    categories: Set[str] = set()
    interests_lower = [i.lower() for i in interests]
    
    for category in INTEREST_CATEGORIES:
        has_match = any(
            tag.lower() in interests_lower 
            for tag in category["tags"]
        )
        if has_match:
            categories.add(category["name"])
    
    return list(categories)


def validate_interests(interests: List[str]) -> Dict[str, List[str]]:
    """Validate if given interests are valid tags."""
    all_tags = [t.lower() for t in get_all_tags()]
    valid = []
    invalid = []
    
    for interest in interests:
        if interest.lower() in all_tags:
            valid.append(interest)
        else:
            invalid.append(interest)
    
    return {"valid": valid, "invalid": invalid}


def get_search_terms_for_interests(interests: List[str]) -> List[str]:
    """Get suggested search terms for given interests."""
    search_terms: Set[str] = set()
    categories = find_categories_for_interests(interests)
    
    # Add the interests themselves
    for i in interests:
        search_terms.add(i)
    
    # Add related category names as context
    for cat in categories:
        search_terms.add(cat)
    
    # Add specific event type keywords based on category
    event_keywords = {
        "Outdoor": ["outdoor events", "nature activities", "adventure tours"],
        "Social Activities": ["social events", "networking events", "happy hours", "meetups"],
        "Hobbies and Passion": ["hobby workshops", "craft classes", "creative events"],
        "Sports and Fitness": ["fitness classes", "sports events", "workout sessions"],
        "Health and Wellbeing": ["wellness events", "meditation sessions", "health workshops"],
        "Technology": ["tech meetups", "hackathons", "startup events", "tech talks"],
        "Art and Culture": ["art exhibitions", "cultural events", "museum exhibits", "performances"],
        "Games": ["gaming events", "esports", "board game nights", "gaming tournaments"],
        "Career and Business": ["business networking", "professional events", "industry conferences"],
        "Science and Education": ["lectures", "educational workshops", "learning events"]
    }
    
    for cat in categories:
        if cat in event_keywords:
            for term in event_keywords[cat]:
                search_terms.add(term)
    
    return list(search_terms)
