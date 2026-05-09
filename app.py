import os
import random
import threading
import time
from datetime import datetime

import pandas as pd
import requests
from flask import Flask, jsonify

# =========================
# KONFIGURACJA
# =========================

URL = "https://track.radantus.com/65ae106a-db60-410d-901d-12cad1b3236b"

# PUBLICZNY RAW URL DO PLIKU CSV NA GITHUB
CSV_URL = "https://raw.githubusercontent.com/radoslawsznajder/grzybiarz-traffic-generator/refs/heads/main/IP_Poland_2.csv"

# Kolumny w CSV
IP_COLUMN = "ip_address"
UA_COLUMN = "user_agent"
REFERER_COLUMN = "referer"

# Interwał requestów
MIN_MINUTES = 5
MAX_MINUTES = 60
TIMEOUT = 30

# Cloudflare Worker do logowania
LOG_ENDPOINT = "https://grzybiarz-traffic-generator.radoslaw-sznajder.workers.dev/"
LOG_API_TOKEN = os.environ["LOG_API_TOKEN"]

app = Flask(__name__)
worker_started = False


# =========================
# ŁADOWANIE CSV Z GITHUB RAW
# =========================

def load_value_pool(csv_url, column_name):
    df = pd.read_csv(csv_url)

    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found. Available: {list(df.columns)}")

    values = (
        df[column_name]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .tolist()
    )

    if not values:
        raise ValueError(f"No values found in column: {column_name}")

    return values


def load_request_pools():
    ip_list = load_value_pool(CSV_URL, IP_COLUMN)
    ua_list = load_value_pool(CSV_URL, UA_COLUMN)
    referer_list = load_value_pool(CSV_URL, REFERER_COLUMN)
    return ip_list, ua_list, referer_list


# =========================
# LOGOWANIE DO CLOUDFLARE WORKER
# =========================

def log_request_remote(timestamp, ip_address, user_agent, referer, status_code, success):
    payload = {
        "timestamp": timestamp,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "referer": referer,
        "status_code": str(status_code),
        "success": bool(success),
    }

    headers = {
        "Authorization": f"Bearer {LOG_API_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(LOG_ENDPOINT, json=payload, headers=headers, timeout=20)
    print(f"[LOG_WORKER] status={response.status_code} body={response.text}", flush=True)
    response.raise_for_status()


# =========================
# REQUEST DO DOCELOWEGO URL
# =========================

def make_request(url, xff_value, user_agent, referer):
    headers = {
        "User-Agent": user_agent,
        "X-Forwarded-For": xff_value,
        "Referer": referer
    }

    timestamp = datetime.now().isoformat(timespec="seconds")

    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        print(
            f"[OK] {timestamp} | {response.status_code} | "
            f"X-Forwarded-For: {xff_value} | UA: {user_agent} | Referer: {referer}",
            flush=True
        )

        try:
            log_request_remote(
                timestamp=timestamp,
                ip_address=xff_value,
                user_agent=user_agent,
                referer=referer,
                status_code=response.status_code,
                success=True,
            )
        except Exception as log_error:
            print(f"[LOG_ERROR] {timestamp} | failed to send log to worker | {log_error}", flush=True)

    except Exception as e:
        print(
            f"[ERROR] {timestamp} | "
            f"X-Forwarded-For: {xff_value} | UA: {user_agent} | Referer: {referer} | {e}",
            flush=True
        )

        try:
            log_request_remote(
                timestamp=timestamp,
                ip_address=xff_value,
                user_agent=user_agent,
                referer=referer,
                status_code="ERROR",
                success=False,
            )
        except Exception as log_error:
            print(f"[LOG_ERROR] {timestamp} | failed to send error log to worker | {log_error}", flush=True)


# =========================
# PĘTLA ROBOCZA
# =========================

def worker_loop():
    print("[BOOT] Worker loop started", flush=True)

    while True:
        try:
            ip_list, ua_list, referer_list = load_request_pools()

            chosen_ip = random.choice(ip_list)
            chosen_ua = random.choice(ua_list)
            chosen_referer = random.choice(referer_list)

            make_request(URL, chosen_ip, chosen_ua, chosen_referer)

            sleep_seconds = random.randint(MIN_MINUTES * 60, MAX_MINUTES * 60)
            print(f"[SLEEP] Sleeping for {sleep_seconds // 60} minutes...", flush=True)
            time.sleep(sleep_seconds)

        except Exception as e:
            print(f"[WORKER_CRASH] {e}", flush=True)
            time.sleep(60)


def start_worker():
    global worker_started
    if not worker_started:
        thread = threading.Thread(target=worker_loop, daemon=True)
        thread.start()
        worker_started = True
        print("[BOOT] Background thread started", flush=True)


# =========================
# ENDPOINTY HTTP DLA RENDER
# =========================

@app.route("/")
def home():
    return "Render app is running", 200


@app.route("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "service": "render-python-app"
    }), 200


@app.route("/test-log")
def test_log():
    timestamp = datetime.now().isoformat(timespec="seconds")

    try:
        log_request_remote(
            timestamp=timestamp,
            ip_address="127.0.0.1",
            user_agent="Render-Test-Agent",
            referer="https://render-test.local",
            status_code="TEST",
            success=True,
        )
        return jsonify({"ok": True, "message": "Test log sent"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


start_worker()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
