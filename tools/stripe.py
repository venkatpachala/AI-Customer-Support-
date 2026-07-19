from typing import Dict

def process_refund(order_id: str, amount: int, reason: str = "damaged") -> Dict:
    """Mock Stripe refund tool"""
    print(f"💳 [Stripe] Processing refund for order {order_id}, amount ₹{amount}")
    
    if amount < 500:
        return {
            "status": "succeeded",
            "refund_id": f"ref_{order_id}",
            "message": "Refund processed automatically"
        }
    else:
        return {
            "status": "requires_approval",
            "refund_id": f"ref_{order_id}",
            "message": "Refund > ₹500 requires manual approval"
        }