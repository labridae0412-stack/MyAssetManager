import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta
import traceback

# --- ページ設定 ---
st.set_page_config(page_title="AI家計簿", layout="wide")

# ==========================================
# ① パスワード入力画面の改善 (スマホ対応)
# ==========================================
# CSSで入力フォームを大きくする
st.markdown("""
<style>
    /* パスワード入力欄を大きくする */
    div[data-testid="stTextInput"] input {
        font-size: 20px;
        padding: 15px;
    }
    /* ボタンも大きくする */
    div[data-testid="stButton"] button {
        height: 3em;
        font-size: 18px;
    }
</style>
""", unsafe_allow_html=True)

# 認証ロジック
if "APP_PASSWORD" in st.secrets:
    # 認証済みかどうかのフラグ
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    if not st.session_state['authenticated']:
        st.title("🔐 ログイン")
        st.write("パスワードを入力してください")
        # サイドバーではなくメイン画面に表示して大きく見やすくする
        password = st.text_input("Password", type="password", key="login_pass")
        
        if st.button("ログイン"):
            if password == st.secrets["APP_PASSWORD"]:
                st.session_state['authenticated'] = True
                st.rerun() # 画面をリロードしてメイン画面へ
            else:
                st.error("パスワードが違います")
        st.stop() # 認証前はここで処理を止める
else:
    st.error("設定エラー: Secretsに 'APP_PASSWORD' を設定してください。")
    st.stop()

# --- 認証通過後のメイン処理 ---
st.title("💰 AI資産管理マネージャー")

# --- サイドバー ---
st.sidebar.header("機能メニュー")
menu = st.sidebar.radio("選択してください", ["レシート登録", "データ確認"])

# --- Session State初期化 ---
if 'input_date' not in st.session_state: st.session_state['input_date'] = date.today()
if 'input_store' not in st.session_state: st.session_state['input_store'] = ""
if 'input_amount' not in st.session_state: st.session_state['input_amount'] = 0
if 'input_category' not in st.session_state: st.session_state['input_category'] = "食費"
if 'input_member' not in st.session_state: st.session_state['input_member'] = "マサ" # 初期値

# --- 定数定義: カテゴリとメンバー ---
CATEGORIES = ["食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", "その他"]
MEMBERS = ["マサ", "ユウ", "ハル"]

# --- 関数: OpenAI解析 ---
def analyze_receipt(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    
    # プロンプト更新: 新しいカテゴリ定義をAIに伝える
    categories_str = "/".join(CATEGORIES)
    system_prompt = f"レシート画像からdate(YYYY-MM-DD),store,amount(数値),category({categories_str})をJSONで抽出せよ。"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if not content: return None, "空の応答"
        return json.loads(content), content
    except Exception as e:
        return None, str(e)

# --- 関数: Google Sheets保存 ---
def save_to_google_sheets(data):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        
        # ★変更: 保存カラムに「対象者(member)」を追加
        # [日付, 店名, カテゴリ, 金額, 対象者, タイムスタンプ]
        row = [
            str(data['date']), 
            data['store'], 
            data['category'], 
            data['amount'], 
            data['member'], 
            str(datetime.now())
        ]
        sheet.append_row(row)
        return True
    except KeyError:
        st.error("Secrets設定エラー: SPREADSHEET_ID")
        return False
    except Exception as e:
        st.error(f"保存エラー: {e}")
        st.text(traceback.format_exc())
        return False

# --- 関数: 会計月の計算 (25日締め) ---
def get_fiscal_month(date_obj):
    # 25日以降なら翌月扱いにする
    # 例: 1/24 -> 1月, 1/25 -> 2月
    if date_obj.day >= 25:
        # 翌月の1日に移動してからフォーマット
        next_month = (date_obj.replace(day=1) + pd.DateOffset(months=1))
        return next_month.strftime('%Y-%m')
    else:
        return date_obj.strftime('%Y-%m')

# ==========================================
# 1. レシート登録画面
# ==========================================
if menu == "レシート登録":
    st.subheader("📸 レシート撮影・登録")
    
    uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])
    
    # 画像解析処理
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロード画像", width=300)
        
        if st.button("🤖 AI解析開始"):
            with st.spinner("AIが読み取っています..."):
                bytes_data = uploaded_file.getvalue()
                result_json, raw_text = analyze_receipt(bytes_data)

                if result_json:
                    st.success("読み取り成功！")
                    try:
                        if result_json.get("date"):
                            st.session_state['input_date'] = datetime.strptime(result_json["date"], "%Y-%m-%d").date()
                        st.session_state['input_store'] = result_json.get("store", "")
                        st.session_state['input_amount'] = int(result_json.get("amount", 0))
                        
                        # カテゴリのマッチング
                        ai_cat = result_json.get("category", "その他")
                        # 部分一致などで既存カテゴリに寄せる
                        matched = "その他"
                        for cat in CATEGORIES:
                            if cat in ai_cat:
                                matched = cat
                                break
                        st.session_state['input_category'] = matched
                        
                    except:
                        pass
                else:
                    st.error("解析失敗。手入力してください。")

    st.markdown("---")
    st.write("### ✏️ 登録フォーム")

    with st.form("entry_form"):
        col1, col2 = st.columns(2)
        
        input_date = col1.date_input("日付", value=st.session_state['input_date'])
        input_store = col2.text_input("店名", value=st.session_state['input_store'])
        input_amount = col1.number_input("金額", min_value=0, value=st.session_state['input_amount'])
        
        # ★変更: カテゴリ選択 (手動追加付き)
        select_options = CATEGORIES + ["➕ 手入力 (新規作成)"]
        try:
            default_idx = select_options.index(st.session_state['input_category'])
        except:
            default_idx = select_options.index("その他")
            
        selected_cat = col2.selectbox("カテゴリ", select_options, index=default_idx)
        
        if selected_cat == "➕ 手入力 (新規作成)":
            final_category = col2.text_input("カテゴリ名を入力", value="")
        else:
            final_category = selected_cat

        # ★変更: 対象者（メンバー）選択プルダウン
        input_member = col1.selectbox("対象者", MEMBERS, index=MEMBERS.index(st.session_state['input_member']) if st.session_state['input_member'] in MEMBERS else 0)

        submitted = st.form_submit_button("✅ 登録する")
        
        if submitted:
            if not final_category:
                st.error("カテゴリ名は必須です")
            else:
                final_data = {
                    "date": input_date,
                    "store": input_store,
                    "amount": input_amount,
                    "category": final_category,
                    "member": input_member
                }
                if save_to_google_sheets(final_data):
                    st.balloons()
                    st.success(f"登録完了: {final_category} ({input_member}) / ¥{input_amount}")

# ==========================================
# 2. データ確認画面 (25日締め集計)
# ==========================================
elif menu == "データ確認":
    st.subheader("📊 月別・対象者別 集計")
    
    if st.button("データを更新"):
        st.cache_data.clear()

    # データ読み込み関数
    def load_data():
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        try:
            spreadsheet_id = st.secrets["SPREADSHEET_ID"]
            sheet = client.open_by_key(spreadsheet_id).sheet1
            data = sheet.get_all_values()
            
            if len(data) <= 1: return pd.DataFrame()

            # データフレーム化 (列数が変わっても対応できるようにロジック修正)
            df = pd.DataFrame(data[1:]) 
            
            # 列定義: 
            # 旧データ(5列): [date, store, category, amount, timestamp]
            # 新データ(6列): [date, store, category, amount, member, timestamp]
            
            # 列数が5なら「member」列を空で挿入して6列に合わせる
            if df.shape[1] == 5:
                df.columns = ["date", "store", "category", "amount", "timestamp"]
                df["member"] = "-" # 旧データはメンバー不明
            elif df.shape[1] >= 6:
                df = df.iloc[:, :6]
                df.columns = ["date", "store", "category", "amount", "member", "timestamp"]
            else:
                return pd.DataFrame() # 列不足

            return df
        except Exception as e:
            st.error(f"読み込みエラー: {e}")
            return None

    df = load_data()

    if df is not None and not df.empty:
        # --- データ前処理 ---
        # 1. 金額の数値化
        df['amount'] = pd.to_numeric(
            df['amount'].astype(str).str.replace(',', '').str.replace('円', ''), 
            errors='coerce'
        ).fillna(0).astype(int)

        # 2. 日付型変換
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date']) # 日付がないデータは除外

        # 3. 会計月（Fiscal Month）の計算: 25日締め
        # applyを使って1行ずつ判定
        df['fiscal_month'] = df['date'].apply(get_fiscal_month)

        # --- 表示コントロール ---
        # 月の選択リスト（新しい順）
        month_list = sorted(df['fiscal_month'].unique(), reverse=True)
        selected_month = st.selectbox("集計する月を選択 (25日〜翌24日)", month_list)

        # 選択された月のデータのみ抽出
        month_df = df[df['fiscal_month'] == selected_month]

        # --- サマリー ---
        total_spend = month_df['amount'].sum()
        st.divider()
        col1, col2, col3 = st.columns(3)
        col1.metric(f"{selected_month}月度の総支出", f"¥{total_spend:,}")
        col2.metric("データ件数", f"{len(month_df)} 件")
        
        # --- グラフ1: カテゴリ別 ---
        st.write("### 🥧 カテゴリ別支出")
        cat_sum = month_df.groupby('category')['amount'].sum().reset_index().sort_values('amount', ascending=False)
        st.bar_chart(cat_sum.set_index('category'))

        # --- グラフ2: 人別 (対象者別) ---
        st.write("### 👤 対象者別支出")
        if 'member' in month_df.columns:
            mem_sum = month_df.groupby('member')['amount'].sum().reset_index().sort_values('amount', ascending=False)
            # 円グラフ風にしたいがStreamlit標準は棒グラフが見やすい
            st.bar_chart(mem_sum.set_index('member'))

        # --- 明細表 ---
        st.write("### 📝 詳細データ")
        st.dataframe(month_df.sort_values('date', ascending=False))
        
    else:
        st.info("データがありません。")
