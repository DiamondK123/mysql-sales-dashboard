import os
import ssl
from datetime import datetime
from zoneinfo import ZoneInfo

import pymysql
from flask import Flask, jsonify, request

app = Flask(__name__)


def get_connection():
    # CA 憑證與連線資訊由主機環境變數取得
    ca_pem = os.environ["MYSQL_CA_PEM"].replace("\\n", "\n")

    tls = ssl.create_default_context(cadata=ca_pem)

    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        ssl=tls,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15,
        read_timeout=20,
        write_timeout=20,
        autocommit=True
    )


@app.after_request
def set_response_headers(response):
    # 僅允許指定的 GitHub Pages 網站跨來源讀取
    allowed_origin = os.environ.get("FRONTEND_ORIGIN", "").rstrip("/")

    if allowed_origin and request.headers.get("Origin") == allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin

    response.headers["Vary"] = "Origin"

    # 每次重新整理都取得最新結果
    response.headers["Cache-Control"] = "no-store"

    return response


@app.get("/")
def home():
    return jsonify({
        "message": "銷售分析 API 已啟動",
        "data_endpoint": "/api/dashboard"
    })


@app.get("/api/dashboard")
def dashboard():
    conn = None

    try:
        conn = get_connection()

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    sale_id,
                    sale_date,
                    product_name,
                    category,
                    channel,
                    unit_price,
                    quantity,
                    returned_quantity
                FROM sales
                ORDER BY sale_date, sale_id
            """)

            rows = cursor.fetchall()

        # 由同一次查詢結果計算摘要與圖表，保持數據一致
        daily = {}
        products = {}
        categories = {}

        quantity_total = 0
        returns_total = 0
        revenue_total = 0

        for row in rows:
            date = row["sale_date"].isoformat()
            product = row["product_name"]
            category = row["category"]

            quantity = int(row["quantity"])
            returns = int(row["returned_quantity"])
            revenue = row["unit_price"] * (quantity - returns)

            quantity_total += quantity
            returns_total += returns
            revenue_total += revenue

            daily[date] = daily.get(date, 0) + revenue
            products[product] = products.get(product, 0) + revenue
            categories[category] = (
                categories.get(category, 0) + revenue
            )

        return jsonify({
            "generated_at": datetime.now(
                ZoneInfo("Asia/Taipei")
            ).isoformat(timespec="seconds"),

            "summary": {
                "record_count": len(rows),
                "total_quantity": quantity_total,
                "total_returns": returns_total,
                "net_revenue": float(revenue_total)
            },

            "daily": [
                {"date": date, "net_revenue": float(value)}
                for date, value in sorted(daily.items())
            ],

            "products": [
                {"name": name, "net_revenue": float(value)}
                for name, value in sorted(
                    products.items(),
                    key=lambda item: item[1],
                    reverse=True
                )
            ],

            "categories": [
                {"name": name, "net_revenue": float(value)}
                for name, value in sorted(categories.items())
            ]
        })

    except Exception:
        app.logger.exception("資料庫查詢失敗")

        return jsonify({
            "error": "暫時無法取得資料，請稍後重試。"
        }), 503

    finally:
        if conn is not None:
            conn.close()
