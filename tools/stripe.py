def process_refund(order_id: str, amount: int = 500, reason: str = "damaged") -> dict:
    print(f"💳 [Stripe] Processing refund for order {order_id}, amount ₹{amount}")
    
    if amount >= 1000:   # Escalate if ≥ ₹1000
        return {
            "status": "requires_approval",
            "refund_id": f"ref_{order_id}",
            "message": "Refund ≥ ₹1000 requires manual approval"
        }
    else:
        return {
            "status": "succeeded",
            "refund_id": f"ref_{order_id}",
            "message": "Refund processed automatically"
        }