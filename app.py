from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import requests
import africastalking
import os
from datetime import datetime
import logging

# This line creates the Flask app instance named 'app'
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# ==================== CONFIGURATION ====================
DARAJA_CONSUMER_KEY = os.getenv("pFxtuFn1bG7bIQkyFwcJJA3e2ROKsBXn0pirnGzGe3VxCwd")
DARAJA_CONSUMER_SECRET = os.getenv("yRNb65OaVb7D3Oe36odcf2j3fZ82kxc7S3tqT7nQQ7VXZknlLtBniTdmFCHBTAAP")
DARAJA_SHORTCODE = os.getenv("NA")

AFRICASTALKING_USERNAME = os.getenv("MutisoNZ", "sandbox")
AFRICASTALKING_API_KEY = os.getenv("atsk_479a7c5a29f4068046f703b1e9c3daa13662d257f9b197a862a142ed6324339b1634af99")

DARAJA_BASE_URL = "https://sandbox.safaricom.co.ke"  # Change to api.safaricom.co.ke for live

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///transactions.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

africastalking.initialize(AFRICASTALKING_USERNAME, AFRICASTALKING_API_KEY)
airtime = africastalking.Airtime
data = africastalking.MobileData

# ==================== DATABASE MODEL ====================
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mpesa_id = db.Column(db.String(50), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    bill_ref = db.Column(db.String(50), default="")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    auto_sent = db.Column(db.Boolean, default=False)
    manually_sent = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

# ==================== PACKAGES ====================
PACKAGES = {
    22: {"type": "airtime", "amount": "KES 22", "name": "45 mins (3 hours)"},
    51: {"type": "airtime", "amount": "KES 51", "name": "50 mins till midnight"},
    10: {"type": "airtime", "amount": "KES 10", "name": "200 SMS (24hrs)"},
    18: {"type": "airtime", "amount": "KES 18", "name": "100 SMS (7 days)"},
    30: {"type": "airtime", "amount": "KES 30", "name": "1000 SMS (7 days)"},
    98: {"type": "airtime", "amount": "KES 98", "name": "1500 SMS (30 days)"},
    19: {"type": "data", "qty": 1000, "unit": "MB", "validity": "Hour", "name": "1GB (1 Hour)"},
    20: {"type": "data", "qty": 250,  "unit": "MB", "validity": "Day",  "name": "250MB (24hrs)"},
    49: {"type": "data", "qty": 350,  "unit": "MB", "validity": "Week", "name": "350MB (7 days)"},
    50: {"type": "data", "qty": 1500, "unit": "MB", "validity": "Hour", "name": "1.5GB (3 Hours)"},
    55: {"type": "data", "qty": 1250, "unit": "MB", "validity": "Day",  "name": "1.25GB Midnight"},
    99: {"type": "data", "qty": 1000, "unit": "MB", "validity": "Day",  "name": "1GB (24hrs)"},
    110:{"type": "data", "qty": 2000, "unit": "MB", "validity": "Day",  "name": "2GB (24hrs)"},
}

# ==================== HELPERS ====================
def normalize_phone(phone):
    if phone.startswith("0"):
        return "+254" + phone[1:]
    elif phone.startswith("254"):
        return "+" + phone
    elif phone.startswith("+"):
        return phone
    return "+254" + phone

def disburse(phone, package):
    try:
        if package["type"] == "airtime":
            response = airtime.send(phone_number=phone, amount=package["amount"])
        else:
            recipients = [{
                "phoneNumber": phone,
                "quantity": package["qty"],
                "unit": package["unit"],
                "validity": package["validity"],
                "productName": "Safaricom Data"
            }]
            response = data.send(recipients=recipients)
        logging.info(f"Success: {response}")
        return True, response
    except Exception as e:
        logging.error(f"Failed: {e}")
        return False, str(e)

# ==================== ROUTES ====================
@app.route("/")
def home():
    return "Airtime & Data Reseller Backend Running! 🚀"

@app.route("/mpesa/validation", methods=["POST"])
def mpesa_validation():
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

@app.route("/mpesa/confirmation", methods=["POST"])
def mpesa_confirmation():
    data = request.get_json()
    mpesa_id = data.get("TransactionID")
    if Transaction.query.filter_by(mpesa_id=mpesa_id).first():
        return jsonify({"ResultCode": 0, "ResultDesc": "Duplicate"})

    amount = float(data.get("TransAmount", 0))
    phone = normalize_phone(data.get("MSISDN", ""))
    bill_ref = data.get("BillRefNumber", "")

    tx = Transaction(mpesa_id=mpesa_id, phone=phone, amount=amount, bill_ref=bill_ref)
    db.session.add(tx)
    db.session.commit()

    package_key = int(amount) if amount == int(amount) else None
    package = PACKAGES.get(package_key)

    if package and phone:
        if package["type"] == "data":
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if Transaction.query.filter(Transaction.phone == phone, Transaction.timestamp >= today, Transaction.auto_sent == True).first():
                tx.auto_sent = False
                db.session.commit()
                return jsonify({"ResultCode": 0, "ResultDesc": "Data limit reached"})

        success, _ = disburse(phone, package)
        tx.auto_sent = success
        db.session.commit()

    return jsonify({"ResultCode": 0, "ResultDesc": "Processed"})

@app.route("/transactions", methods=["GET"])
def get_transactions():
    txs = Transaction.query.order_by(Transaction.timestamp.desc()).limit(50).all()
    return jsonify([{
        "id": t.id,
        "mpesa_id": t.mpesa_id,
        "phone": t.phone,
        "amount": t.amount,
        "time": t.timestamp.strftime("%Y-%m-%d %H:%M"),
        "auto_sent": t.auto_sent,
        "manually_sent": t.manually_sent
    } for t in txs])

@app.route("/manual-disburse", methods=["POST"])
def manual_disburse():
    payload = request.get_json()
    tx_id = payload.get("tx_id")
    package_amount = payload.get("package_amount")

    tx = Transaction.query.get(tx_id)
    if not tx or tx.manually_sent:
        return jsonify({"success": False, "message": "Invalid or already sent"})

    package = PACKAGES.get(package_amount)
    if not package:
        return jsonify({"success": False, "message": "Package not found"})

    success, msg = disburse(tx.phone, package)
    if success:
        tx.manually_sent = True
        db.session.commit()

    return jsonify({"success": success, "message": msg or "Success"})

# This is required for local testing only
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)