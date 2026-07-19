from typing import Dict
import json

class CustomerMemory:
    def __init__(self):
        self.memory = {}  # In real: use Postgres

    def get_customer_context(self, customer_id: str) -> Dict:
        if customer_id not in self.memory:
            self.memory[customer_id] = {
                "previous_orders": ["#12345"],
                "preferences": {"language": "en"},
                "vip_status": False
            }
        return self.memory[customer_id]

    def update(self, customer_id: str, key: str, value):
        if customer_id in self.memory:
            self.memory[customer_id][key] = value

customer_memory = CustomerMemory()