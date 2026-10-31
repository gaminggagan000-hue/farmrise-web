import os, time, uuid, json, requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="PhanthomXhub FarmRise App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FIXED_DEVICE = {
    "id": "f0e1d2c3b4a59687",
    "model": "OnePlus 8T",
    "brand": "OnePlus",
    "name": "OnePlus8T",
    "android": "11"
}
FIXED_LOCATION = {
    "lat": "17.3850440",
    "long": "78.4866710",
    "city": "Hyderabad",
    "state": "TELANGANA"
}

BASE_NEW = "https://api.new.farmrise.bayer.com"
BASE_PUBLIC = "https://api.public.farmrise.bayer.com"
APP_VERSION = "2.72.6"

def get_headers(session_data, extra_headers=None):
    dev = FIXED_DEVICE
    loc = FIXED_LOCATION
    h = {
        "appversion": APP_VERSION,
        "countryisocode": "IN",
        "languageid": "1",
        "languageiso": "en",
        "user-agent": f"Dalvik/2.1.0 (Linux; U; Android {dev['android']}; {dev['model']})",
        "accept-encoding": "gzip",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "requestid": str(uuid.uuid4()),
        "deviceid": dev["id"],
        "latitude": loc["lat"],
        "longitude": loc["long"],
        "state": loc["state"],
        "role": "FARMER"
    }
    if session_data.get("acquired_user_id"):
        h["acquireduserid"] = session_data["acquired_user_id"]
    if session_data.get("registered_user_id"):
        h["registereduserid"] = session_data["registered_user_id"]
    if session_data.get("security_token"):
        h["authorization"] = session_data["security_token"]
    if extra_headers:
        h.update(extra_headers)
    return h

class SendOTPReq(BaseModel):
    phone: str

class VerifyOTPReq(BaseModel):
    phone: str
    otp: str
    acquired_user_id: str

class ClaimRewardReq(BaseModel):
    phone: str
    security_token: str
    registered_user_id: str
    reward_id: str
    upi: str

@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>PhanthomXhub App Running! Put index.html in same folder.</h1>"

@app.post("/api/send-otp")
def send_otp(req: SendOTPReq):
    h = get_headers({})
    acq_resp = requests.post(
        f"{BASE_PUBLIC}/v1/acquired_users",
        json={"deviceId": FIXED_DEVICE["id"], "languageId": "1", "termsAndConditionsId": "35", "userSourceBO": {"utmMedium": "organic", "utmSource": "google-play"}},
        headers=h, timeout=15
    )
    if acq_resp.status_code not in (200, 201):
        raise HTTPException(status_code=400, detail="Failed to acquire user")
    
    acq_id = acq_resp.json()["data"]["acquiredUserId"]
    
    h_otp = get_headers({"acquired_user_id": acq_id})
    r = requests.post(f"{BASE_NEW}/v1/challenge", json={"phoneNumber": f"+91{req.phone}", "whatsappOTPConsent": True}, headers=h_otp, timeout=15)
    
    if r.status_code == 200:
        return {"success": True, "message": "OTP sent successfully", "acquired_user_id": acq_id}
    raise HTTPException(status_code=400, detail="OTP Send Failed")

@app.post("/api/verify-otp")
def verify_otp(req: VerifyOTPReq):
    h = get_headers({"acquired_user_id": req.acquired_user_id})
    r = requests.post(f"{BASE_NEW}/v1/verify_challenge", json={"otp": req.otp, "phoneNumber": req.phone}, headers=h, timeout=15)
    
    if r.status_code in (200, 201):
        data = r.json()["data"]
        sec_token = data.get("securityToken")
        reg_user_id = data.get("registeredUserId")
        
        h_auth = get_headers({"security_token": sec_token, "registered_user_id": reg_user_id})
        rew_resp = requests.get(f"{BASE_NEW}/farmer_reward_service/v2/user/{reg_user_id}/rewards/unclaimed", headers=h_auth, timeout=15)
        rewards = rew_resp.json().get("data", []) if rew_resp.status_code == 200 else []
        
        return {
            "success": True,
            "security_token": sec_token,
            "registered_user_id": reg_user_id,
            "rewards": rewards,
            "has_unclaimed": len(rewards) > 0
        }
    raise HTTPException(status_code=400, detail="Invalid OTP")

@app.post("/api/claim")
def claim(req: ClaimRewardReq):
    h = get_headers({"security_token": req.security_token, "registered_user_id": req.registered_user_id})
    requests.post(f"{BASE_NEW}/farmer_reward_service/v1/user/scratchcard/scratched", json={"registeredUserId": req.registered_user_id, "rewardId": req.reward_id}, headers=h, timeout=15)
    requests.put(f"{BASE_NEW}/farmer_reward_service/v1/users/{req.registered_user_id}/paymentAccounts", json={"mobileNumber": req.phone, "paymentMethod": "UPI", "paymentPlatform": "PHONEPE", "upiId": req.upi, "userId": req.registered_user_id}, headers=h, timeout=15)
    payout_res = requests.post(f"{BASE_NEW}/farmer_reward_service/v1/reward/payments/payout", json={"paymentMethod": "UPI", "registeredUserId": req.registered_user_id, "rewardEventId": req.reward_id, "upiId": req.upi}, headers=h, timeout=15)
    
    if payout_res.status_code == 200:
        return {"success": True, "status": payout_res.json().get("data", {}).get("paymentStatus", "CLAIM_IN_PROCESS")}
    raise HTTPException(status_code=400, detail="Payout Claim Failed")