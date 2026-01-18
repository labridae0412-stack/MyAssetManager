import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="CSV一括登録", layout="wide")
utils.check_password()

# ==========================================
# 🔒 セキュリティロック機能
# ==========================================
env = st.secrets.get("ENVIRONMENT", "cloud")

if env != "local":
    st.error("⛔ セキュリティ制限")
    st.warning("""
    **この機能はセキュリティのため、Web版（クラウド）では無効化されています。**
    
    銀行データの登録を行う場合は、自宅PCのローカル環境でアプリを起動してください。
    (VSCode Terminal: `streamlit run Home.py`)
    """)
    st.stop()

# ==========================================
# 画面描画
# ==========================================
st.title("📥 金融機関データ取込")
st.markdown("各金融機関のCSVを取り込み、**収支区分(Cat1)** と **費目(Cat2)** に分けて登録します。")
st.info("⚠️ スプレッドシートの列構成が `[日付, 店名, 収支, 費目, 金額...]` になっていることを確認してください。")

# 1. 設定選択
col1, col2 = st.columns(2)
institution_name = col1.selectbox("🏦 金融機関を選択", list(utils.INSTITUTION_CONFIG.keys()))
selected_member = col2.selectbox("👤 誰のデータですか？", utils.MEMBERS, index=0)

config = utils.INSTITUTION_CONFIG[institution_name]
target_sheet = config["sheet_name"]

st.info(f"保存先DB: **{target_sheet}** / 読み込み設定: {config['encoding']}")

# 2. ファイルアップロード
uploaded_file = st.file_uploader(f"{institution_name} のCSVをアップロード", type=["csv"])

if uploaded_file:
    try:
        # 設定された文字コードで読み込み
        df = pd.read_csv(uploaded_file, encoding=config["encoding"])
        
        # データ整形用のリスト
        processed_rows = []

        # -----------------------------------------------------
        # A. 2列構成 (支出列 / 収入列) の場合: M銀行など
        # -----------------------------------------------------
        if "expense_col" in config and "income_col" in config:
            required_cols = [config["date_col"], config["store_col"], config["expense_col"], config["income_col"]]
            missing_cols = [c for c in required_cols if c not in df.columns]
            
            if missing_cols:
                st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
            else:
                for index, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    store_val = str(row[config["store_col"]]).strip() if pd.notna(row[config["store_col"]]) else ""
                    if pd.isna(date_val): continue

                    # 1. 支出列チェック
                    exp_str = str(row[config["expense_col"]]).replace(',', '').replace('円', '')
                    try:
                        exp_amount = int(float(exp_str)) if exp_str and exp_str != 'nan' else 0
                    except:
                        exp_amount = 0
                    
                    if exp_amount > 0:
                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": "支出",
                            "category_2": "未分類",
                            "amount": abs(exp_amount),
                            "member": selected_member
                        })

                    # 2. 収入列チェック
                    inc_str = str(row[config["income_col"]]).replace(',', '').replace('円', '')
                    try:
                        inc_amount = int(float(inc_str)) if inc_str and inc_str != 'nan' else 0
                    except:
                        inc_amount = 0
                    
                    if inc_amount > 0:
                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": "収入",
                            "category_2": "その他",
                            "amount": abs(inc_amount),
                            "member": selected_member
                        })

        # -----------------------------------------------------
        # B. 1列構成 (入出金が1列 or 支出のみ) の場合: 他の銀行
        # -----------------------------------------------------
        else:
            required_cols = [config["date_col"], config["store_col"], config["amount_col"]]
            missing_cols = [c for c in required_cols if c not in df.columns]
            
            if missing_cols:
                st.error(f"エラー: CSV内に以下の列名が見つかりません。\n{missing_cols}")
            else:
                for index, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    store_val = str(row[config["store_col"]]).strip() if pd.notna(row[config["store_col"]]) else ""
                    if pd.isna(date_val): continue

                    amount_str = str(row[config["amount_col"]]).replace(',', '').replace('円', '')
                    try:
                        amount_raw = int(float(amount_str)) if amount_str and amount_str != 'nan' else 0
                    except:
                        amount_raw = 0
                    
                    if amount_raw != 0:
                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": "支出",
                            "category_2": "未分類",
                            "amount": abs(amount_raw),
                            "member": selected_member
                        })

        # --- 結果の表示と保存 ---
        if processed_rows:
            import_df = pd.DataFrame(processed_rows)
            
            st.write("### プレビュー (確認)")
            st.caption("※この時点では重複チェックは行われていません。登録ボタンを押した時に判定されます。")
            
            edited_df = st.data_editor(
                import_df,
                num_rows="dynamic",
                column_config={
                    "date": st.column_config.DateColumn("日付"),
                    "category_1": st.column_config.SelectboxColumn("収支区分", options=["支出", "収入"]),
                    "category_2": st.column_config.SelectboxColumn("費目(Cat2)", options=utils.CATEGORIES + ["その他"]),
                    "amount": st.column_config.NumberColumn("金額")
                },
                hide_index=True,
                key="editor"
            )
            
            if st.button(f"✅ {target_sheet} に登録実行"):
                # 戻り値が3つに変更されました: 成功フラグ, 追加件数, スキップ件数
                success, added_count, skipped_count = utils.save_bulk_to_google_sheets(edited_df, target_sheet)
                
                if success:
                    st.balloons()
                    msg = f"登録完了！\n- **{added_count}** 件を新規登録しました。\n"
                    if skipped_count > 0:
                        msg += f"- **{skipped_count}** 件は重複のためスキップされました。"
                    
                    if added_count > 0:
                        st.success(msg)
                    else:
                        st.warning(msg) # 全て重複の場合は警告色で見やすく
                else:
                    st.error(f"登録失敗: {added_count}") # エラー時は第2引数にメッセージが入る
        else:
            st.warning("読み込めるデータがありませんでした。")

    except Exception as e:
        st.error(f"読み込みエラー: {e}")