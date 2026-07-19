from typing import Dict

def get_order_details(order_id: str) -> Dict:
    """Mock Shopify tool - replace with real API later"""
    print(f"🔧 [Shopify] Fetching order {order_id}")
    return {
        "order_id": order_id,
        "status": "delivered",
        "damage_reported": True,
        "return_eligible": True
    }

def initiate_return(order_id: str, reason: str) -> Dict:
    """Mock return initiation"""
    print(f"🔧 [Shopify] Initiating return for {order_id} - Reason: {reason}")
    return {
        "return_id": f"RET-{order_id}",
        "status": "approved",
        "message": "Return initiated successfully"
    }