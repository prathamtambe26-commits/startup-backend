from fastapi import FastAPI, Request, Form
from fastapi.responses import PlainTextResponse
from supabase import create_client, Client
from twilio.twiml.messaging_response import MessagingResponse
import os
import re
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  INIT
# ─────────────────────────────────────────────
app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─────────────────────────────────────────────
#  CATEGORY KEYWORDS MAP
# ─────────────────────────────────────────────
CATEGORY_MAP = {
    "food":        ["food", "pizza", "burger", "lunch", "dinner", "breakfast",
                    "tea", "coffee", "snack", "swiggy", "zomato", "biryani",
                    "rice", "roti", "dal", "veg", "chicken"],
    "transport":   ["uber", "ola", "bus", "auto", "cab", "petrol", "fuel",
                    "train", "metro", "bike", "rickshaw"],
    "shopping":    ["shopping", "clothes", "shirt", "shoes", "amazon",
                    "flipkart", "dress", "bag", "watch"],
    "health":      ["medicine", "doctor", "hospital", "medical", "pharmacy",
                    "gym", "health"],
    "bills":       ["bill", "electricity", "water", "rent", "internet",
                    "recharge", "mobile", "wifi"],
    "entertainment": ["movie", "netflix", "spotify", "game", "cricket",
                      "party", "outing", "fun"],
    "income":      ["got", "received", "salary", "income", "bonus",
                    "freelance", "payment", "earned", "cashback"],
}

# ─────────────────────────────────────────────
#  HELPER: Categorize a message
#  e.g.  "pizza 150"  →  ("pizza", 150, "food", "expense")
#        "got 5000"   →  ("got",  5000, "income", "income")
# ─────────────────────────────────────────────
def parse_expense(text: str):
    text = text.strip().lower()

    # Extract amount — last number in the string
    numbers = re.findall(r'\d+\.?\d*', text)
    if not numbers:
        return None
    amount = float(numbers[-1])

    # Keyword = everything before the number
    keyword = re.sub(r'\d+\.?\d*', '', text).strip()
    if not keyword:
        keyword = text

    # Detect category
    category = "other"
    tx_type  = "expense"

    for cat, keywords in CATEGORY_MAP.items():
        for kw in keywords:
            if kw in keyword:
                category = cat
                if cat == "income":
                    tx_type = "income"
                break

    return {
        "keyword":  keyword,
        "amount":   amount,
        "category": category,
        "type":     tx_type,
    }

# ─────────────────────────────────────────────
#  HELPER: Fetch user by phone
# ─────────────────────────────────────────────
def get_user(phone: str):
    res = supabase.table("users").select("*").eq("phone_number", phone).limit(1).execute()
    return res.data[0] if res.data else None

# ─────────────────────────────────────────────
#  HELPER: Build expense summary
# ─────────────────────────────────────────────
def build_summary(user_id: str, name: str) -> str:
    res = supabase.table("transaction").select("*").eq("user_id", user_id).execute()
    transactions = res.data

    if not transactions:
        return "📭 No transactions recorded yet!"

    total_income  = sum(t["amount"] for t in transactions if t["type"] == "income")
    total_expense = sum(t["amount"] for t in transactions if t["type"] == "expense")
    balance       = total_income - total_expense

    # Group expenses by category
    cat_totals = {}
    for t in transactions:
        if t["type"] == "expense":
            cat = t["category"]
            cat_totals[cat] = cat_totals.get(cat, 0) + t["amount"]

    cat_lines = "\n".join(
        f"   • {cat.capitalize()}: ₹{amt:.0f}"
        for cat, amt in sorted(cat_totals.items(), key=lambda x: -x[1])
    )

    summary = (
        f"📊 *{name}'s Expense Report*\n"
        f"{'─'*28}\n"
        f"💰 Total Income:  ₹{total_income:.0f}\n"
        f"💸 Total Expense: ₹{total_expense:.0f}\n"
        f"🏦 Balance:       ₹{balance:.0f}\n"
        f"{'─'*28}\n"
        f"📂 *By Category:*\n{cat_lines if cat_lines else '   None yet'}\n"
        f"{'─'*28}\n"
        f"📝 *Last 5 Transactions:*\n"
    )

    for t in transactions[-5:][::-1]:
        icon = "🟢" if t["type"] == "income" else "🔴"
        summary += f"   {icon} {t['keyword'].capitalize()} — ₹{t['amount']:.0f}\n"

    return summary

# ─────────────────────────────────────────────
#  WEBHOOK  (Twilio sends POST here)
# ─────────────────────────────────────────────
@app.post("/webhook", response_class=PlainTextResponse)
async def webhook(
    Body: str = Form(...),
    From: str = Form(...),
):
    incoming_msg = Body.strip()
    # Twilio sends number as "whatsapp:+919876543210"
    phone = From.replace("whatsapp:", "").strip()

    resp = MessagingResponse()
    msg  = resp.message

    user = get_user(phone)

    # ── CASE 1: Brand new user ──────────────────
    if not user:
        if incoming_msg.lower() == "hi":
            # Create a pending row (state = awaiting_name)
            supabase.table("users").insert({
                "phone_number": phone,
                "name":         "",
                "state":        "awaiting_name"
            }).execute()
            msg("👋 Welcome! To register, please *enter your name*.")
        else:
            msg("👋 Hello! Please send *hi* to get started.")
        return str(resp)

    state = user.get("state", "active")
    user_id = user["id"]

    # ── CASE 2: Waiting for name input ──────────
    if state == "awaiting_name":
        # Save candidate name, ask for confirmation
        supabase.table("users").update({
            "name":  incoming_msg,
            "state": "awaiting_confirmation"
        }).eq("id", user_id).execute()

        msg(
            f"You entered: *{incoming_msg}*\n\n"
            f"Is this correct? Reply *yes* to confirm or *no* to re-enter."
        )
        return str(resp)

    # ── CASE 3: Waiting for name confirmation ───
    if state == "awaiting_confirmation":
        if incoming_msg.lower() in ["yes", "y"]:
            supabase.table("users").update({"state": "active"}).eq("id", user_id).execute()
            name = user["name"]
            msg(
                f"✅ Registered successfully! Welcome *{name}*! 🎉\n\n"
                f"You can now track expenses. Just send messages like:\n"
                f"  • *pizza 150*\n"
                f"  • *got 5000* (for income)\n"
                f"  • *expense* (to see your report)"
            )
        else:
            supabase.table("users").update({
                "name":  "",
                "state": "awaiting_name"
            }).eq("id", user_id).execute()
            msg("No problem! Please *enter your name* again.")
        return str(resp)

    # ── CASE 4: Active user ──────────────────────
    if state == "active":
        name = user["name"]

        # Show expense report
        if incoming_msg.lower() in ["expense", "report", "summary", "balance"]:
            summary = build_summary(user_id, name)
            msg(summary)
            return str(resp)

        # Help message
        if incoming_msg.lower() in ["help", "hi", "hello"]:
            msg(
                f"👋 Hi *{name}*! Here's what you can do:\n\n"
                f"💸 *Add expense:* pizza 150\n"
                f"💰 *Add income:*  got 5000\n"
                f"📊 *View report:* expense\n"
            )
            return str(resp)

        # Try to parse as transaction
        parsed = parse_expense(incoming_msg)
        if parsed:
            supabase.table("transaction").insert({
                "user_id":  user_id,
                "amount":   parsed["amount"],
                "keyword":  parsed["keyword"],
                "category": parsed["category"],
                "type":     parsed["type"],
            }).execute()

            icon = "💰" if parsed["type"] == "income" else "💸"
            msg(
                f"{icon} Recorded!\n"
                f"  *{parsed['keyword'].capitalize()}* — ₹{parsed['amount']:.0f}\n"
                f"  Category: {parsed['category'].capitalize()}\n"
                f"  Type: {parsed['type'].capitalize()}\n\n"
                f"Send *expense* to see your full report."
            )
        else:
            msg(
                f"❓ Couldn't understand that.\n\n"
                f"Try: *pizza 150* or *got 5000*\n"
                f"Or send *help* for all commands."
            )

    return str(resp)


# ─────────────────────────────────────────────
#  RUN  →  uvicorn main:app --reload
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
