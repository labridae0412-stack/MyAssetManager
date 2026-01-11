import streamlit as st
import pandas as pd
from datetime import datetime, date
import utils # 共通機能を読み込み

st.set_page_config(page_title="レシート登録", layout="wide")

# ★全ページでログインチェックを行う
utils.check_password()

st.title("📸 レシート撮影・登録")

# --- Session State初期化 ---
if 'input_date' not in st.session_state: st.session_state['input_date'] = date.today()
if 'input_store' not in st.session_state: st.session_state['input_store'] = ""
if 'input_amount' not in st.session_state: st.session_state['input_amount'] = 0
if 'input_category' not in st.session_state: st.session_state['input_category'] = "食費"
if 'input_member' not in st.session_state: st.session_state['input_member'] = ""
if 'split_data' not in st.session_state: st.session_state['split_data'] = None

reg_mode = st.radio("登録モードを選択", ["1. 合計で登録 (一括)", "2. 明細ごとに登録 (分割)"])
uploaded_file = st.file_uploader("レシート画像をアップロード", type=["jpg", "png", "jpeg"])

# --- 分割モード ---
if reg_mode == "2. 明細ごとに登録 (分割)":
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロード画像", width=300)
        
        if st.button("🤖 AI解析 (明細読み取り)"):
            with st.spinner("商品ごとの明細を読み取っています..."):
                bytes_data = uploaded_file.getvalue()
                # utilsの関数を使用
                result_json, raw_text = utils.analyze_receipt(bytes_data, mode="split")
                
                if result_json and "items" in result_json:
                    st.success(f"{len(result_json['items'])} 件の明細を検出しました。")
                    
                    items = result_json['items']
                    date_str = result_json.get("date", str(date.today()))
                    try:
                        default_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except:
                        default_date = date.today()

                    store_val = result_json.get("store", "")
                    
                    init_data = []
                    for item in items:
                        init_data.append({
                            "利用日": default_date,
                            "店名": store_val,
                            "商品名(メモ)": item.get("name", ""),
                            "金額": item.get("amount", 0),
                            "カテゴリ": "食費",
                            "対象者": ""
                        })
                    
                    df_split = pd.DataFrame(init_data)
                    if not df_split.empty:
                        df_split["利用日"] = pd.to_datetime(df_split["利用日"]).dt.date

                    st.session_state['split_data'] = df_split
                else:
                    st.error("明細読み取り失敗。合計モードを試してください。")
        
        if st.session_state['split_data'] is not None:
            st.write("### 📝 明細の編集・登録")
            
            edited_df = st.data_editor(
                st.session_state['split_data'],
                num_rows="dynamic",
                column_config={
                    "利用日": st.column_config.DateColumn("日付", format="YYYY-MM-DD"),
                    "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=utils.CATEGORIES+["その他"], required=True),
                    "対象者": st.column_config.SelectboxColumn("対象者", options=[""]+utils.MEMBERS, required=False),
                    "金額": st.column_config.NumberColumn("金額", format="%d円")
                },
                hide_index=True
            )
            
            if st.button("✅ 全て登録する"):
                success_count = 0
                for index, row in edited_df.iterrows():
                    save_data = {
                        "date": row["利用日"],
                        "store": row["店名"] + " (" + row["商品名(メモ)"] + ")",
                        "category": row["カテゴリ"],
                        "amount": row["金額"],
                        "member": row["対象者"] if row["対象者"] else ""
                    }
                    if utils.save_to_google_sheets(save_data):
                        success_count += 1
                
                if success_count > 0:
                    st.balloons()
                    st.success(f"{success_count} 件登録しました！")
                    st.session_state['split_data'] = None

# --- 一括モード ---
else:
    if uploaded_file is not None:
        st.image(uploaded_file, caption="アップロード画像", width=300)
        
        if st.button("🤖 AI解析開始"):
            with st.spinner("合計金額を読み取っています..."):
                bytes_data = uploaded_file.getvalue()
                result_json, raw_text = utils.analyze_receipt(bytes_data, mode="total")

                if result_json:
                    st.success("読み取り成功！")
                    try:
                        if result_json.get("date"):
                            st.session_state['input_date'] = datetime.strptime(result_json["date"], "%Y-%m-%d").date()
                        st.session_state['input_store'] = result_json.get("store", "")
                        st.session_state['input_amount'] = int(result_json.get("amount", 0))
                        
                        ai_cat = result_json.get("category", "その他")
                        matched = "その他"
                        for cat in utils.CATEGORIES:
                            if cat in ai_cat: matched = cat
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
        
        select_options = utils.CATEGORIES + ["➕ 手入力 (新規作成)"]
        try:
            default_idx = select_options.index(st.session_state['input_category'])
        except:
            default_idx = select_options.index("その他")
        selected_cat = col2.selectbox("カテゴリ", select_options, index=default_idx)
        
        if selected_cat == "➕ 手入力 (新規作成)":
            final_category = col2.text_input("カテゴリ名を入力", value="")
        else:
            final_category = selected_cat

        member_options = [""] + utils.MEMBERS
        current_mem = st.session_state['input_member']
        mem_idx = member_options.index(current_mem) if current_mem in member_options else 0
        input_member = col1.selectbox("対象者 (任意)", member_options, index=mem_idx)

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
                if utils.save_to_google_sheets(final_data):
                    st.balloons()
                    msg_cat = final_category
                    if input_member: msg_cat += f"({input_member})"
                    st.success(f"登録完了: {msg_cat} / ¥{input_amount}")