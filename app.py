
import json
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data.json"
data_lock = Lock()


def load_data():
    if not DATA_FILE.exists():
        return {
            "transactions": [],
            "budgets": [],
            "goals": []
        }

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        for key in ("transactions", "budgets", "goals"):
            if not isinstance(data.get(key), list):
                data[key] = []

        return data

    except (json.JSONDecodeError, OSError):
        raise RuntimeError(
            "Không đọc được data.json. "
            "Hãy sao lưu và kiểm tra file dữ liệu."
        )


def save_data(data):
    temporary_file = DATA_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temporary_file, DATA_FILE)


def valid_money(value, allow_zero=False):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None

    if amount < 0 or (amount == 0 and not allow_zero):
        return None

    if not amount < float("inf"):
        return None

    if amount != amount:
        return None

    return amount


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/data")
def get_data():
    with data_lock:
        return jsonify(load_data())


@app.post("/api/transactions")
def add_transaction():
    payload = request.get_json(silent=True) or {}

    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    tx_type = payload.get("type")
    tx_date = str(payload.get("date", ""))

    amount = valid_money(payload.get("amount"))

    if not name or not category:
        return jsonify(error="Vui lòng nhập tên và danh mục."), 400

    if tx_type not in ("income", "expense"):
        return jsonify(error="Loại giao dịch không hợp lệ."), 400

    if amount is None:
        return jsonify(error="Số tiền không hợp lệ."), 400

    if len(tx_date) != 10:
        return jsonify(error="Ngày giao dịch không hợp lệ."), 400

    transaction = {
        "id": str(uuid4()),
        "name": name,
        "category": category,
        "type": tx_type,
        "amount": amount,
        "date": tx_date,
        "note": str(payload.get("note", "")).strip()
    }

    with data_lock:
        data = load_data()
        data["transactions"].append(transaction)
        save_data(data)

    return jsonify(transaction), 201


@app.put("/api/transactions/<transaction_id>")
def update_transaction(transaction_id):
    payload = request.get_json(silent=True) or {}

    with data_lock:
        data = load_data()
        transaction = next(
            (
                item for item in data["transactions"]
                if item["id"] == transaction_id
            ),
            None
        )

        if transaction is None:
            return jsonify(error="Không tìm thấy giao dịch."), 404

        name = str(payload.get("name", "")).strip()
        category = str(payload.get("category", "")).strip()
        tx_type = payload.get("type")
        tx_date = str(payload.get("date", ""))
        amount = valid_money(payload.get("amount"))

        if not name or not category:
            return jsonify(error="Thiếu tên hoặc danh mục."), 400

        if tx_type not in ("income", "expense"):
            return jsonify(error="Loại giao dịch không hợp lệ."), 400

        if amount is None or len(tx_date) != 10:
            return jsonify(error="Số tiền hoặc ngày không hợp lệ."), 400

        transaction.update({
            "name": name,
            "category": category,
            "type": tx_type,
            "amount": amount,
            "date": tx_date,
            "note": str(payload.get("note", "")).strip()
        })

        save_data(data)

    return jsonify(transaction)


@app.delete("/api/transactions/<transaction_id>")
def delete_transaction(transaction_id):
    with data_lock:
        data = load_data()
        original_count = len(data["transactions"])

        data["transactions"] = [
            item for item in data["transactions"]
            if item["id"] != transaction_id
        ]

        if len(data["transactions"]) == original_count:
            return jsonify(error="Không tìm thấy giao dịch."), 404

        save_data(data)

    return jsonify(ok=True)


@app.put("/api/collection/<collection_name>/<item_id>")
def update_collection_item(collection_name, item_id):
    if collection_name not in ("budgets", "goals"):
        return jsonify(error="Danh sách không hợp lệ."), 400

    payload = request.get_json(silent=True) or {}

    with data_lock:
        data = load_data()
        item = next(
            (
                entry for entry in data[collection_name]
                if entry["id"] == item_id
            ),
            None
        )

        if item is None:
            return jsonify(error="Không tìm thấy mục cần sửa."), 404

        for field in ("name", "category", "due"):
            if field in payload:
                item[field] = str(payload[field]).strip()

        for field in ("limit", "target", "saved"):
            if field in payload:
                amount = valid_money(
                    payload[field],
                    allow_zero=(field == "saved")
                )

                if amount is None:
                    return jsonify(
                        error=f"Giá trị {field} không hợp lệ."
                    ), 400

                item[field] = amount

        save_data(data)

    return jsonify(item)


@app.post("/api/collection/<collection_name>")
def add_collection_item(collection_name):
    if collection_name not in ("budgets", "goals"):
        return jsonify(error="Danh sách không hợp lệ."), 400

    payload = request.get_json(silent=True) or {}

    if collection_name == "budgets":
        category = str(payload.get("category", "")).strip()
        amount = valid_money(payload.get("limit"))

        if not category or amount is None:
            return jsonify(error="Danh mục hoặc hạn mức không hợp lệ."), 400

        item = {
            "id": str(uuid4()),
            "category": category,
            "limit": amount
        }

    else:
        name = str(payload.get("name", "")).strip()
        target = valid_money(payload.get("target"))
        saved = valid_money(payload.get("saved", 0), allow_zero=True)

        if not name or target is None or saved is None:
            return jsonify(error="Thông tin mục tiêu không hợp lệ."), 400

        item = {
            "id": str(uuid4()),
            "name": name,
            "target": target,
            "saved": saved,
            "due": str(payload.get("due", ""))
        }

    with data_lock:
        data = load_data()
        data[collection_name].append(item)
        save_data(data)

    return jsonify(item), 201


@app.delete("/api/collection/<collection_name>/<item_id>")
def delete_collection_item(collection_name, item_id):
    if collection_name not in ("budgets", "goals"):
        return jsonify(error="Danh sách không hợp lệ."), 400

    with data_lock:
        data = load_data()
        original_count = len(data[collection_name])

        data[collection_name] = [
            item for item in data[collection_name]
            if item["id"] != item_id
        ]

        if len(data[collection_name]) == original_count:
            return jsonify(error="Không tìm thấy mục cần xóa."), 404

        save_data(data)

    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5001,
        debug=False
    )
