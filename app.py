import base64
import json
import os
import requests
import pandas as pd
from flask import Flask, render_template, request
from dotenv import load_dotenv
import uuid
from flask import request, Response
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

VALID_USER = os.getenv("AUTH_USER", "admin")
VALID_PASS = os.getenv("AUTH_PASS", "password")

def auth_required():
    request_id = str(uuid.uuid4())
    auth = request.authorization
    logger.debug(f"[{request_id}] Authorization header: {auth}")
    if not auth:
        logger.error(f"[{request_id}] No authorization header provided")
        return Response('Unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    if auth.username != VALID_USER or auth.password != VALID_PASS:
        logger.error(f"[{request_id}] Invalid credentials: username={auth.username}, expected={VALID_USER}")
        return Response('Unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    logger.debug(f"[{request_id}] Authentication successful")
    return None


load_dotenv()
app = Flask(__name__)

USERNAME = os.getenv('AVALARA_USERNAME')
PASSWORD = os.getenv('AVALARA_PASSWORD')
COMPANY_ID = os.getenv('AVALARA_COMPANY_ID')
API_URL = f"https://quoting.xbo.dev.avalara.io/api/v2/companies/{COMPANY_ID}/globalcompliance"

def run_calculate(products, export_country, import_country, clearance_type, catalogue_lookup):
    results = []
    debug = []
    value = 799.0 if clearance_type == "Type 86" else 801.0
    total_qty = sum(p.get("quantity", 1) for p in products)
    unit_value = value / total_qty
    lines = []

    for idx, p in enumerate(products):
        desc = p["description"]
        coo = p.get("coo")
        quantity = p.get("quantity", 1)
        preference = p.get("preferenceProgramApplicable", False)
        hs = p.get("hs_code") or catalogue_lookup.get(desc, {}).get("hs_code", "00000000")
        category = p.get("category") or catalogue_lookup.get(desc, {}).get("category", "General")

        item_params = [{"name": "price", "value": str(round(unit_value, 2)), "unit": "USD"}]
        line_params = item_params + [
            {"name": "length", "value": "10", "unit": "in"},
            {"name": "width", "value": "6", "unit": "in"},
            {"name": "height", "value": "4", "unit": "in"},
            {"name": "weight", "value": "1.11", "unit": "lb"},
            {"name": "SHIPPING", "value": 8.88, "unit": "USD"},
            {"name": "HANDLING", "value": 3.33, "unit": "USD"},
            {"name": "INSURANCE", "value": 2.22, "unit": "USD"}
        ]
        if coo:
            item_params.append({"name": "coo", "value": coo, "unit": ""})
            line_params.append({"name": "coo", "value": coo, "unit": ""})

        lines.append({
            "lineNumber": idx + 1,
            "quantity": quantity,
            "preferenceProgramApplicable": preference,
            "item": {
                "itemCode": str(idx + 1),
                "description": desc,
                "itemGroup": category,
                "classifications": [{"country": "DE", "hscode": hs}],
                "classificationParameters": item_params,
                "parameters": []
            },
            "classificationParameters": line_params
        })

    payload = {
        "id": "calculate",
        "companyId": int(COMPANY_ID),
        "currency": "USD",
        "sellerCode": "SC8104341",
        "shipFrom": {"country": export_country},
        "destinations": [{
            "shipTo": {"country": import_country, "region": "MA"},
            "parameters": [
                {"name": "SPECIAL_CALC2", "value": "DUTY_ONLY", "unit": ""},
                {"name": "SHIPPING", "value": "3", "unit": "USD"},
                {"name": "HANDLING", "value": "5", "unit": "USD"},
                {"name": "INSURANCE", "value": "3", "unit": "USD"}
            ],
            "taxRegistered": False
        }],
        "lines": lines,
        "type": "QUOTE_MAXIMUM",
        "storeMerchandiseTypes": ["Toys"],
        "disableCalculationSummary": False,
        "restrictionsCheck": True,
        "program": "Regular"
    }

    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode(),
        "Content-Type": "application/json"
    }

    response = requests.post(API_URL, headers=headers, json=payload)
    response_json = response.json()

    for i, line in enumerate(response_json['globalCompliance'][0]['quote']['lines']):
        duty_calc = line.get("calculationSummary", {}).get("dutyCalculationSummary", [])
        duty_applied = next((d.get("value") for d in duty_calc if d.get("name") == "DUTY_DEMINIMIS_APPLIED"), "false")
        if duty_applied == "true":
            duty_rate = 0.0
        else:
            duty_rate = next((float(d.get("value", 0)) for d in duty_calc if d.get("name") == "RATE"), 0.0)

        tax_rate = max((c.get("rate", 0.0) for c in line.get("costLines", []) if c["type"] == "TAX"), default=0.0)
        total_rate = duty_rate + tax_rate
        results.append({
            **products[i],
            "duty_rate": f"{round(duty_rate * 100, 2)}%",
            "tax_rate": f"{round(tax_rate * 100, 2)}%",
            "total_rate": f"{round(total_rate * 100, 2)}%",
            "restrictions": []
        })

    debug = json.dumps(response_json, indent=2)
    return results, debug

#COO Optimizer

def run_optimize_coo(products, export_country, import_country, clearance_type, catalogue_lookup):
    results = []
    debug_summary = []

    for idx, p in enumerate(products[:3]):
        desc = p['description']
        quantity = p.get('quantity', 1)
        value = 799.0 / quantity if clearance_type == "Type 86" else 801.0 / quantity
        preference = p.get("preferenceProgramApplicable", False)
        hs_code = p.get("hs_code") or catalogue_lookup.get(desc, {}).get("hs_code", "000000")
        category = p.get("category") or catalogue_lookup.get(desc, {}).get("category", "General")
        coo_results = []

        for coo in ["Not Specified", "CA", "MX", "CN", "VN"]:
            try:
                classification_item = [{"name": "price", "value": str(round(value, 2)), "unit": "USD"}]
                classification_line = [
                    {"name": "price", "value": str(round(value, 2)), "unit": "USD"},
                    {"name": "length", "value": "10", "unit": "in"},
                    {"name": "width", "value": "6", "unit": "in"},
                    {"name": "height", "value": "4", "unit": "in"},
                    {"name": "weight", "value": "1.11", "unit": "lb"},
                    {"name": "SHIPPING", "value": 8.88, "unit": "USD"},
                    {"name": "HANDLING", "value": 3.33, "unit": "USD"},
                    {"name": "INSURANCE", "value": 2.22, "unit": "USD"}
                ]
                if coo != "Not Specified":
                    classification_item.append({"name": "coo", "value": coo, "unit": ""})
                item = {
                    "lineNumber": 1,
                    "quantity": quantity,
                    "preferenceProgramApplicable": preference,
                    "item": {
                        "itemCode": str(idx + 1),
                        "description": desc,
                        "itemGroup": category,
                        "classifications": [{"country": "DE", "hscode": hs_code}],
                        "classificationParameters": classification_item,
                        "parameters": []
                    },
                    "classificationParameters": classification_line
                }

                payload = {
                    "id": f"optimize-{idx}-{coo}",
                    "companyId": int(COMPANY_ID),
                    "currency": "USD",
                    "sellerCode": "SC8104341",
                    "shipFrom": {"country": export_country},
                    "destinations": [{
                        "shipTo": {"country": import_country, "region": "MA"},
                        "parameters": [
                            {"name": "SPECIAL_CALC2", "value": "DUTY_ONLY", "unit": ""},
                            {"name": "SHIPPING", "value": "3", "unit": "USD"},
                            {"name": "HANDLING", "value": "5", "unit": "USD"},
                            {"name": "INSURANCE", "value": "3", "unit": "USD"}
                        ],
                        "taxRegistered": False
                    }],
                    "lines": [item],
                    "type": "QUOTE_MAXIMUM",
                    "storeMerchandiseTypes": ["Toys"],
                    "disableCalculationSummary": False,
                    "restrictionsCheck": True,
                    "program": "Regular"
                }

                headers = {
                    "Authorization": "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode(),
                    "Content-Type": "application/json"
                }

                response = requests.post(API_URL, headers=headers, json=payload)
                line = response.json()['globalCompliance'][0]['quote']['lines'][0]
                duty_calc = line.get("calculationSummary", {}).get("dutyCalculationSummary", [])
                duty_applied = next((d.get("value") for d in duty_calc if d.get("name") == "DUTY_DEMINIMIS_APPLIED"), "false")
                if duty_applied == "true":
                    duty_rate = 0.0
                else:
                    duty_rate = next((float(d.get("value", 0)) for d in duty_calc if d.get("name") == "RATE"), 0.0)

                tax_rate = max((c.get("rate", 0.0) for c in line.get("costLines", []) if c["type"] == "TAX"), default=0.0)
                total_rate = duty_rate + tax_rate

                coo_results.append({
                    "coo": coo,
                    "duty": duty_rate,
                    "tax": tax_rate,
                    "total": total_rate
                })
            except Exception as e:
                print(f"[ERROR] {desc} COO={coo} → {e}")

        coo_results.sort(key=lambda x: x["total"])
        best = coo_results[0]
        results.append({
            "description": desc,
            "hs_code": hs_code,
            "coo": best["coo"],
            "quantity": quantity,
            "category": category,
            "preferenceProgramApplicable": preference,
            "duty_rate": f"{round(best['duty'] * 100, 2)}%",
            "tax_rate": f"{round(best['tax'] * 100, 2)}%",
            "total_rate": f"{round(best['total'] * 100, 2)}%",
            "coo_comparisons": coo_results,
            "restrictions": []
        })
        debug_summary.append({
            "description": desc,
            "best_coo": best["coo"],
            "coo_comparisons": coo_results
        })

    return results, json.dumps(debug_summary, indent=2)

# main function call

@app.route('/', methods=['GET', 'POST'])
def index():
    products = []
    products_with_results = []
    response_debug = None

    auth_error = auth_required()
    if auth_error:
        return auth_error

    # Load catalogue
    df = pd.read_excel("catalogue.xlsx")
    catalogue_lookup = {
        row["DESC COMMODITY"]: {
            "hs_code": str(row["HS CODE"]),
            "category": row["CATEGORY"]
        }
        for _, row in df.iterrows()
    }

    if request.method == 'POST':
        export_country = request.form['export_country']
        import_country = request.form['import_country']
        clearance_type = request.form['clearance_type']
        action = request.form.get('action', 'calculate')
        print("[DEBUG] Action submitted:", action)
        products = json.loads(request.form['product_data'])

        if action == "optimize":
            products_with_results, response_debug = run_optimize_coo(
                products, export_country, import_country, clearance_type, catalogue_lookup
            )
        else:
            products_with_results, response_debug = run_calculate(
                products, export_country, import_country, clearance_type, catalogue_lookup
            )

    return render_template(
        'index.html',
        results=products_with_results,
        debug=response_debug,
        original=products,
        catalogue=catalogue_lookup
    )

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
