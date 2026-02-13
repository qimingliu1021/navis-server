from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, START, END
from state import ItineraryState
from nodes import scout_node, explorer_node, planner_node

# Create the graph
workflow = StateGraph(ItineraryState)

# Add nodes
workflow.add_node("scout", scout_node)
workflow.add_node("explorer", explorer_node)
workflow.add_node("planner", planner_node)

# Add edges
workflow.add_edge(START, "scout")
workflow.add_edge("scout", "explorer")
workflow.add_edge("explorer", "planner")
workflow.add_edge("planner", END)

# Compile graph
app = workflow.compile()

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    
    async def main():
        print("Running manual test...")
        initial_state = {
            "city": "San Francisco",
            "interests": ["tech events", "AI hackathons"],
            "start_date": "2026-05-20",
            "end_date": "2026-05-22",
            "logs": []
        }
        
        async for output in app.astream(initial_state):
            for key, value in output.items():
                print(f"Node '{key}':")
                print(f"  - Logs: {value.get('logs', [])}")
                if key == "planner":
                    print(f"  - Events: {len(value.get('itinerary', []))}")

    asyncio.run(main())
