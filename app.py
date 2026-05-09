import csv
import os
import random
import threading
import time
from datetime import datetime

import pandas as pd
import requests
from flask import Flask

URL = "https://track.radantus.com/65ae106a-db60-410d-901d-12cad1b3236b"

FILE_URL = "https://raw.githubusercontent.com/radoslawsznajder/grzybiarz-traffic-generator/refs/heads/main/IP_Poland_2.csv"

IP_COLUMN = "ip_address"
UA_COLUMN = "user_agent"
REFERER_COLUMN = "referer"

LOG_FILE = "request_log.csv"
MIN_MINUTES = 5
MAX_MINUTES = 60
TIMEOUT = 30

app = Flask(__name__)
worker_started = False


def load_value_pool(file_url, column_name):
    df = pd.read_csv(file_url)

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


def load_request_pools(file_url, ip_column, ua_column, referer_column):
    ip_list = load_value_pool(file_url, ip_column)
    ua_list = load_value_pool(file_url, ua_column)
    referer_list = load_value_pool(file_url, referer_column)
    return ip_list, ua_list, referer_list


def ensure_log_file(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "ip_address",
                    "user_agent",
                    "referer",
                    "status_code",
                    "success",
                ]
            )
            writer.writeheader()


def log_request(path, timestamp, ip_address, user_agent, referer, status_code, success):
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "ip_address",
                "user_agent",
                "referer",
                "status_code",
                "success",
            ]
        )
        writer.writerow({
            "timestamp": timestamp,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "referer": referer,
            "status_code": status_code,
            "success": success
        })


def make_request(url, xff_value, user_agent, referer, log_file):
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
        log_request(log_file, timestamp, xff_value, user_agent, referer, response.status_code, True)
    except Exception as e:
        print(
            f"[ERROR] {timestamp} | "
            f"X-Forwarded-For: {xff_value} | UA: {user_agent} | Referer: {referer} | {e}",
            flush=True
        )
        log_request(log_file, timestamp, xff_value, user_agent, referer, "ERROR", False)


def worker_loop():
    try:
        ip_list, ua_list, referer_list = load_request_pools(
            FILE_URL,
            IP_COLUMN,
            UA_COLUMN,
            REFERER_COLUMN
        )

        ensure_log_file(LOG_FILE)

        while True:
            chosen_ip = random.choice(ip_list)
            chosen_ua = random.choice(ua_list)
            chosen_referer = random.choice(referer_list)

            make_request(URL, chosen_ip, chosen_ua, chosen_referer, LOG_FILE)

            sleep_seconds = random.randint(MIN_MINUTES * 60, MAX_MINUTES * 60)
            print(f"Sleeping for {sleep_seconds // 60} minutes...", flush=True)
            time.sleep(sleep_seconds)

    except Exception as e:
        print(f"Worker crashed: {e}", flush=True)


@app.route("/")
def home():
    return "Worker is running"


@app.route("/healthz")
def healthz():
    return "OK", 200


def start_worker():
    global worker_started
    if not worker_started:
        thread = threading.Thread(target=worker_loop, daemon=True)
        thread.start()
        worker_started = True


start_worker()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
