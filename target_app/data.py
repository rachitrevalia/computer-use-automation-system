"""
In-memory "database" for the mock targteted app.
"""
MEMBERS = {
    "12345": {"id": "12345", "name": "Alice Johnson", "savings_balance": 4210.55, "locked": False},
    "67890": {"id": "67890", "name": "John Doe", "savings_balance": 152.00, "locked": False},
    "99999": {"id": "99999", "name": "Locked Account Corp", "savings_balance": 0.0, "locked": True},
}

SUB_ACCOUNTS = {}

def get_member(member_id):
    return MEMBERS.get(member_id)

def open_sub_account(member_id,account_type,intial_deposit):
    SUB_ACCOUNTS.setdefault(member_id,[])
    new_id = f"SUB-{member_id}-{len(SUB_ACCOUNTS[member_id])+ 1}"
    record = {"sub_account_id":new_id, "type":account_type, "deposit":intial_deposit}
    SUB_ACCOUNTS[member_id].append(record)
    return record