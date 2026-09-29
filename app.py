import asyncio
import time
import requests
import json
import sys
import os
from flask import Flask, request, jsonify
try:
    from flask_cors import CORS
    HAS_CORS = True
except ImportError:
    HAS_CORS = False
from Crypto.Cipher import AES
from datetime import datetime, timedelta
from google.protobuf import json_format
import urllib3
urllib3.disable_warnings()

# ============= Protobuf Imports =============
try:
    import FreeFire_pb2, main_pb2, AccountPersonalShow_pb2
    print("✅ Proto files imported successfully")
except ImportError as e:
    print(f"❌ Proto import error: {e}")
    sys.exit(1)

# =============================================
# CONFIG & SECRETS
# =============================================
RELEASEVERSION = "OB55"
USERAGENT = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
MAIN_KEY = b'Yg&tc%DEuh6%Zc^8'
MAIN_IV = b'6oyZDr22E3ychjM%'

ACCOUNT_CREDENTIALS = {
    "IND": {
        "uid": "7943649152",
        "password": "1219443E419AD8761270FCB2CF0649AF2C40A6B0286F9466E16DC4D09CED42D3"
    },
    "BD": {
        "uid": "7904662856",
        "password": "GeneratedBy@ChannelLinkBox_JbAI3K68yIR2_RiduanCodex"
    },
    "BR": {
        "uid": "7810756496",
        "password": "507D3250C779A4E73A74B66998E99DD4ED95A6133A07151FC0411A225C405ADD"
    }
}

REGION_CONFIG = {
    "IND": {"server_url": "https://client.ind.freefiremobile.com", "release_version": "OB55"},
    "BD": {"server_url": "https://clientbp.ppmainecoonghj.com", "release_version": "OB55"},
    "BR": {"server_url": "https://client.us.freefiremobile.com", "release_version": "OB55"}
}

REGION_PRIORITY = ["IND", "BD", "BR"]

app = Flask(__name__)
if HAS_CORS:
    CORS(app)
else:
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = '*'
        response.headers['Access-Control-Allow-Methods'] = '*'
        return response

# In-Memory Token Cache (cached for 7 hours per region)
_token_cache = {}

# =============================================
# AES & Protobuf Helpers
# =============================================
def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(plaintext))

def try_parse_login_res(data: bytes):
    try:
        msg = FreeFire_pb2.LoginRes()
        msg.ParseFromString(data)
        if msg.account_id and msg.account_id > 0:
            return json.loads(json_format.MessageToJson(msg))
    except Exception:
        pass
    return None

def extract_login_res(raw: bytes) -> dict:
    parsed = try_parse_login_res(raw)
    if parsed:
        return parsed
    idx = 0
    while True:
        idx = raw.find(b"\x08", idx)
        if idx == -1:
            break
        parsed = try_parse_login_res(raw[idx:])
        if parsed:
            return parsed
        idx += 1
    jwt_marker = raw.find(b"eyJhbGciOiJIUzI1NiIs")
    if jwt_marker != -1:
        for i in range(jwt_marker - 1, max(jwt_marker - 300, -1), -1):
            if raw[i] == 0x42:
                parsed = try_parse_login_res(raw[i:])
                if parsed:
                    return parsed
                break
    raise Exception(f"Could not parse LoginRes. Raw: {raw[:200]}")

# =============================================
# Autonomous Garena Session Generation
# =============================================
def generate_garena_session(region: str = "IND"):
    cred = ACCOUNT_CREDENTIALS.get(region, ACCOUNT_CREDENTIALS["IND"])
    oauth_url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = {
        "uid": cred["uid"],
        "password": cred["password"],
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    headers = {
        "User-Agent": USERAGENT,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    oauth_res = requests.post(oauth_url, data=payload, headers=headers, timeout=10)
    if oauth_res.status_code != 200:
        print(f"❌ OAuth grant failed for {region}: {oauth_res.status_code}")
        return None

    oauth_data = oauth_res.json()
    open_id = oauth_data.get("open_id")
    access_token = oauth_data.get("access_token")
    if not open_id or not access_token:
        print(f"❌ Missing open_id or access_token in OAuth response for {region}")
        return None

    req = FreeFire_pb2.LoginReq()
    req.open_id = open_id
    req.open_id_type = "4"
    req.login_token = access_token
    req.orign_platform_type = "4"

    proto_bytes = req.SerializeToString()
    enc_payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)

    major_headers = {
        "User-Agent": USERAGENT,
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-Ga-Sv": "1789534056",
        "Authorization": "Bearer",
        "X-Ga": "v1 1",
        "Releaseversion": RELEASEVERSION,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
        "PlAy_VeR": "1.132.1",
        "Ob_VeR": RELEASEVERSION,
    }

    major_res = requests.post("https://loginbp.ppmainecoonghj.com/MajorLogin", data=enc_payload, headers=major_headers, timeout=10)
    if major_res.status_code != 200:
        print(f"❌ MajorLogin failed for {region}: {major_res.status_code}, content: {major_res.content[:50]}")
        return None

    parsed_res = extract_login_res(major_res.content)
    token = parsed_res.get("token")
    if not token:
        print(f"❌ No token in MajorLogin parsed result for {region}")
        return None

    server_url = REGION_CONFIG.get(region, REGION_CONFIG["IND"])["server_url"]
    token_info = {
        "token": f"Bearer {token}",
        "region": region,
        "server_url": server_url,
        "expires_at": time.time() + 25200
    }
    _token_cache[region] = token_info
    print(f"✅ Generated fresh Garena session token for region {region}")
    return token_info

def get_token(region: str):
    cached = _token_cache.get(region)
    if cached and cached.get("expires_at", 0) > time.time():
        return cached
    return generate_garena_session(region)

# =============================================
# Fetch Free Fire Player Profile
# =============================================
def GetAccountInformation(uid: int, region: str):
    try:
        token_info = get_token(region)
        if not token_info:
            return None

        server_url = token_info["server_url"]
        token = token_info["token"]

        show_req = main_pb2.GetPlayerPersonalShow()
        show_req.a = uid
        show_req.b = 7

        enc_payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, show_req.SerializeToString())

        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Authorization": token,
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": RELEASEVERSION,
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "Keep-Alive"
        }

        resp = requests.post(f"{server_url}/GetPlayerPersonalShow", data=enc_payload, headers=headers, timeout=6)
        if resp.status_code != 200:
            return None

        pb_res = AccountPersonalShow_pb2.AccountPersonalShowInfo()
        pb_res.ParseFromString(resp.content)
        result = json.loads(json_format.MessageToJson(pb_res))
        result["region"] = region
        return result
    except Exception as e:
        print(f"❌ Error in GetAccountInformation for UID {uid} in {region}: {e}")
        return None

# =============================================
# Helper Formatters
# =============================================
def get_item_name(item_id):
    if not item_id or item_id == "0" or item_id == 0:
        return "N/A"
    return str(item_id)

def get_rank_name(rp):
    try:
        rp = int(rp)
    except:
        return "N/A"
    if rp == 0: return "Bronze I"
    if rp < 100: return "Bronze II"
    if rp < 200: return "Bronze III"
    if rp < 300: return "Silver I"
    if rp < 400: return "Silver II"
    if rp < 500: return "Silver III"
    if rp < 600: return "Gold I"
    if rp < 700: return "Gold II"
    if rp < 800: return "Gold III"
    if rp < 900: return "Platinum I"
    if rp < 1000: return "Platinum II"
    if rp < 1100: return "Platinum III"
    if rp < 1200: return "Diamond I"
    if rp < 1300: return "Diamond II"
    if rp < 1400: return "Diamond III"
    if rp < 1500: return "Heroic"
    if rp < 2000: return "Master"
    return "Grandmaster"

def ts_to_bst(ts):
    try:
        dt = datetime.fromtimestamp(int(ts)) + timedelta(hours=5, minutes=30)
        return dt.strftime("%d %b %Y at %I:%M:%S %p") + " (IST)"
    except:
        return "N/A"

# =============================================
# API Routes
# =============================================
@app.route('/info', methods=['GET'])
def get_full_info():
    uid_str = request.args.get('uid', '').strip()
    if not uid_str:
        return jsonify({"error": "UID required"}), 400

    try:
        uid_int = int(uid_str)
    except ValueError:
        return jsonify({"error": "Invalid UID format"}), 400

    account_data = None
    for region in REGION_PRIORITY:
        account_data = GetAccountInformation(uid_int, region)
        if account_data and (account_data.get("basicInfo") or account_data.get("basic_info")):
            break

    if not account_data:
        return jsonify({"error": "Player not found or Garena servers unreachable", "uid": uid_str}), 404

    used_region = account_data.get("region", "IND")
    basic = account_data.get("basicInfo", {})
    clan = account_data.get("clanBasicInfo", {})
    social = account_data.get("socialInfo", {})
    pet = account_data.get("petInfo", {})
    captain = account_data.get("captainBasicInfo", {})
    credit = account_data.get("creditScoreInfo", {})

    response = {
        "status": "success",
        "server_used": used_region,
        "BanStatus": "🔴 BANNED" if account_data.get("isBanned") else "🟢 UNBANNED",
        "BasicInformation": {
            "PrimeLevel": "N/A",
            "Name": basic.get("nickname", "N/A"),
            "UID": uid_str,
            "Level": basic.get("level", "N/A"),
            "Exp": basic.get("exp", "N/A"),
            "Region": basic.get("region", used_region),
            "Likes": basic.get("liked", "N/A"),
            "HonorScore": credit.get("score", credit.get("creditScore", 100)),
            "CelebrityStatus": "Yes" if basic.get("showBrRank") else "No",
            "Title": get_item_name(basic.get("title", "0")),
            "Signature": social.get("socialHighlight", social.get("signature", "N/A"))
        },
        "ActivityInformation": {
            "MostRecentOB": basic.get("releaseVersion", RELEASEVERSION),
            "BooyahPass": "Yes" if basic.get("hasElitePass") else "No",
            "CurrentBpBadges": basic.get("badgeCnt", "N/A"),
            "BRRank": get_rank_name(basic.get("rankingPoints", 0)),
            "BRPoints": basic.get("rankingPoints", 0),
            "ShowBRRank": "True" if basic.get("showBrRank") else "False",
            "ShowCSRank": "True" if basic.get("showCsRank") else "False",
            "CreatedAt": ts_to_bst(basic.get("createAt", 0)),
            "LastLogin": ts_to_bst(basic.get("lastLoginAt", 0))
        },
        "GuildInformation": {
            "GuildName": clan.get("clanName", "No Guild"),
            "GuildID": clan.get("clanId", "N/A"),
            "GuildLevel": clan.get("clanLevel", "N/A"),
            "LiveMembers": clan.get("memberNum", clan.get("currentMembers", "N/A")),
            "MaxMembers": clan.get("capacity", clan.get("maxMembers", "N/A"))
        },
        "PetDetails": {
            "Equipped": "Yes" if pet.get("isSelected") else "No",
            "PetNick": pet.get("petName", pet.get("name", "N/A")),
            "PetType": get_item_name(pet.get("petId", "0")),
            "PetSkill": get_item_name(pet.get("selectedSkillId", "0")),
            "PetSkin": get_item_name(pet.get("skinId", "0")),
            "PetExp": pet.get("exp", "N/A"),
            "PetLevel": pet.get("level", "N/A")
        },
        "LeaderInformation": {
            "Name": captain.get("nickname", "N/A"),
            "UID": captain.get("accountId", "N/A"),
            "Level": captain.get("level", "N/A"),
            "Region": captain.get("region", "N/A"),
            "BooyahPass": "Yes" if captain.get("hasElitePass") else "No",
            "CreatedAt": ts_to_bst(captain.get("createAt", 0)),
            "LastLogin": ts_to_bst(captain.get("lastLoginAt", 0)),
            "MostRecentOB": captain.get("releaseVersion", "N/A"),
            "Title": get_item_name(captain.get("title", "0")),
            "BpBadges": captain.get("badgeCnt", "N/A"),
            "BRRank": get_rank_name(captain.get("rankingPoints", 0)),
            "BRPoints": captain.get("rankingPoints", 0)
        }
    }

    return jsonify(response)

@app.route('/token', methods=['GET'])
def get_jwt_token_endpoint():
    region = request.args.get('region', 'IND').upper()
    tok_info = get_token(region)
    if tok_info:
        return jsonify(tok_info)
    return jsonify({"error": "Failed to generate token"}), 500

@app.route('/status', methods=['GET'])
def token_status():
    status = {}
    for reg, info in _token_cache.items():
        expires_in = info['expires_at'] - time.time()
        status[reg] = {"has_token": True, "expires_in_hours": round(expires_in / 3600, 2)}
    return jsonify({"total_tokens": len(_token_cache), "tokens": status})

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "running",
        "service": "ff-gateway",
        "version": RELEASEVERSION,
        "endpoint": "/info?uid=UID"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5004, debug=False)