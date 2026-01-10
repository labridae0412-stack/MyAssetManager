import streamlit as st
import base64
import json
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- 関数: OpenAIで画像を解析 ---
def analyze_receipt(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    response = client.chat.completions.create(
        model="gpt-4o", 
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "このレシート画像を解析し、以下の情報をJSON形式で抽出してください。\nキー名: date (YYYY-MM-DD), store (店名), amount (合計金額・数値のみ), category (食費, 日用品, 交通費, その他 のいずれか)\n余計な解説は不要で、JSONデータのみを返してください。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ],
            }
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 関数: Google Sheetsへ保存 ---
def save_to_google_sheets(data):
    # Secretsから認証情報を読み込む
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        # シート名は環境に合わせて変更してください
        sheet = client.open("Kakeibo_DB").sheet1 
        
        # 行を追加: [日付, 店名, カテゴリ, 金額, 決済方法, 対象者, 登録日時]
        # ※Phase 2対応で項目を少し増やしています
        row = [
            data.get('date'), 
            data.get('store'), 
            data.get('category'), 
            data.get('amount'),
            data.get('payment_method', '-'), # 新規追加
            data.get('user', '-'),           # 新規追加
            str(datetime.now())
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"スプレッドシートへの保存に失敗しました: {e}")
        return False