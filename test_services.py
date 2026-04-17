import asyncio
from services.routing import OSMRoutingService  # adjust import

async def test_route():
    # Sample coordinates (Bangalore example)
    waypoints = [
        (77.5946, 12.9716),
        (77.6090, 12.9600)
    ]
    osmr=OSMRoutingService()
    route_data = await osmr.get_route(waypoints)

    print("Full Route Data:")
    print(route_data)

    if route_data and "routes" in route_data:
        route = route_data["routes"][0]
        print("Distance (km):", route["distance"] / 1000)
        print("Duration (minutes):", route["duration"] / 60)

asyncio.run(test_route())
