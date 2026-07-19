from typing import Dict

def process_refund(order_id: str, amount: int = 500, reason: str = "damaged") -> Dict:
    """
    Mock Stripe refund tool
    """
    print(f"[Stripe] Processing refund for order {order_id}, amount ₹{amount}")

    if amount >= 1000:
        return {
            "status": "requires_approval",
            "refund_id": f"ref_{order_id}",
            "message": f"Refund of ₹{amount} requires manual approval",
            "amount": amount
        }

    return {
        "status": "succeeded",
        "refund_id": f"ref_{order_id}",
        "message": "Refund processed automatically",
        "amount": amount
    }