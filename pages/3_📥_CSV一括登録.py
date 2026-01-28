import streamlit as st
import pandas as pd
import utils
from datetime import date

st.set_page_config(page_title="CSV一括登録", layout="wide")
utils.check_password()

if st.secrets.get("ENVIRONMENT", "cloud") != "local":
    st.error("⛔ セキュリティ制限: ローカル環境でのみ実行可能です")
    st.stop()

st.title("📥 金融機関データ取込")

# --- マスタ管理 ---
with st.sidebar:
    st.header("⚙️ マスタ管理")
    if st.button("🔄 過去データからマスタを初期作成"):
        with st.spinner("解析中..."):
            count = utils.create_master_from_history()
            st.success(f"{count} 件登録しました")

st.markdown("各金融機関のCSVを取り込み、**収支区分(Cat1)** と **費目(Cat2)** に分けて登録します。")

# 設定選択
col1, col2 = st.columns(2)
institution_name = col1.selectbox("🏦 金融機関を選択", list(utils.INSTITUTION_CONFIG.keys()))
selected_member_default = col2.selectbox("👤 デフォルトの対象者", utils.MEMBERS, index=0)

config = utils.INSTITUTION_CONFIG[institution_name]
target_sheet = config["sheet_name"]
master_dict = utils.load_category_master()

st.caption(f"保存先: **{target_sheet}** / 設定: {config['encoding']}")

# ファイルアップロード
uploaded_files = st.file_uploader(
    f"{institution_name} のCSV (複数選択可)", 
    type=["csv"], 
    accept_multiple_files=True
)

if uploaded_files:
    all_processed_rows = []
    
    for uploaded_file in uploaded_files:
        try:
            df = pd.DataFrame()
            target_date = None
            
            # --- A. 特殊ローダー ---
            if "custom_loader" in config:
                if config["custom_loader"] == "rakuten_sec_balance":
                    df = utils.load_rakuten_securities_csv(uploaded_file, config["encoding"])
                    if df is not None:
                        file_date = utils.extract_date_from_filename(uploaded_file.name)
                        if file_date:
                            target_date = file_date
                        else:
                            st.warning(f"⚠️ {uploaded_file.name}: 日付不明のため本日の日付を使用")
                            target_date = date.today()
                        df["entry_date"] = target_date

            # --- B. 通常ローダー ---
            else:
                df = pd.read_csv(uploaded_file, encoding=config["encoding"])
            
            if df is None or df.empty: continue
            
            # --- データ整形 ---
            # 1. R証券
            if "custom_loader" in config and config["custom_loader"] == "rakuten_sec_balance":
                type_col = "種別"
                name_col = "銘柄"
                val_col = "時価評価額[円]"
                if name_col not in df.columns and "銘柄コード・ティッカー" in df.columns:
                    name_col = "銘柄コード・ティッカー"
                
                if val_col in df.columns:
                    for _, row in df.iterrows():
                        val_str = str(row.get(val_col, "0")).replace(',', '').replace('円', '')
                        try: amount_val = int(float(val_str))
                        except: amount_val = 0
                        
                        if amount_val > 0:
                            all_processed_rows.append({
                                "date": row["entry_date"],
                                "store": row.get(name_col, ""),
                                "category_1": "資産",
                                "category_2": row.get(type_col, "その他"),
                                "amount": amount_val,
                                "member": selected_member_default,
                                "institution": institution_name,
                                "balance": None # 残高列は空
                            })

            # 2. Rカード (利用者列対応)
            elif "member_col" in config:
                for _, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    if pd.isna(date_val): continue
                    
                    store_val = str(row[config["store_col"]]).strip()
                    
                    amt_str = str(row[config["amount_col"]]).replace(',', '').replace('円', '')
                    try: amount_val = int(float(amt_str))
                    except: continue
                    
                    csv_member = str(row[config["member_col"]]).strip()
                    member_val = csv_member if csv_member else selected_member_default
                    suggested_cat = utils.suggest_category(store_val, master_dict)

                    all_processed_rows.append({
                        "date": date_val,
                        "store": store_val,
                        "category_1": "支出",
                        "category_2": suggested_cat,
                        "amount": amount_val,
                        "member": member_val,
                        "institution": institution_name,
                        "balance": "" 
                    })

            # 3. その他銀行
            else:
                is_2col = ("expense_col" in config)
                for _, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    if pd.isna(date_val): continue
                    store_val = str(row[config["store_col"]]).strip() if pd.notna(row[config["store_col"]]) else ""
                    
                    bal_val = ""
                    if "balance_col" in config and config["balance_col"] in df.columns:
                        b_str = str(row[config["balance_col"]]).replace(',', '')
                        try: bal_val = int(float(b_str))
                        except: pass
                    
                    amt = 0
                    cat1 = "支出"
                    if is_2col:
                        e_str = str(row[config["expense_col"]]).replace(',', '')
                        i_str = str(row[config["income_col"]]).replace(',', '')
                        e_amt = int(float(e_str)) if e_str and e_str!='nan' else 0
                        i_amt = int(float(i_str)) if i_str and i_str!='nan' else 0
                        if e_amt > 0: amt, cat1 = e_amt, "支出"
                        elif i_amt > 0: amt, cat1 = i_amt, "収入"
                    else:
                        a_str = str(row[config["amount_col"]]).replace(',', '')
                        raw_amt = int(float(a_str)) if a_str and a_str!='nan' else 0
                        amt = abs(raw_amt)
                        cat1 = "支出" if raw_amt < 0 else "収入"
                    
                    if amt > 0:
                        suggested_cat = utils.suggest_category(store_val, master_dict)
                        if cat1 == "収入" and suggested_cat == "未分類": suggested_cat = "その他"

                        all_processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": cat1,
                            "category_2": suggested_cat,
                            "amount": amt,
                            "member": selected_member_default,
                            "institution": institution_name,
                            "balance": bal_val
                        })

        except Exception as e:
            st.error(f"❌ {uploaded_file.name}: 処理エラー - {e}")

    # --- 結果表示と保存 ---
    if all_processed_rows:
        import_df = pd.DataFrame(all_processed_rows).sort_values(by="date")
        
        st.write(f"### プレビュー (全 {len(uploaded_files)} ファイル分)")
        
        edited_df = st.data_editor(
            import_df,
            num_rows="dynamic",
            column_config={
                "date": st.column_config.DateColumn("日付"),
                "category_1": st.column_config.SelectboxColumn("収支/区分", options=["支出", "収入", "資産"]),
                "category_2": st.column_config.SelectboxColumn("費目/種別", options=utils.CATEGORIES),
                "amount": st.column_config.NumberColumn("金額/評価額"),
                "institution": st.column_config.TextColumn("金融機関", disabled=True),
                "balance": st.column_config.NumberColumn("残高")
            },
            hide_index=True, key="editor"
        )
        
        if st.button(f"✅ {target_sheet} に一括登録実行"):
            # ★修正: シンプルな戻り値受け取り
            success, added_count, skipped_count = utils.save_bulk_to_google_sheets(edited_df, target_sheet, institution_name)
            
            if success:
                st.balloons()
                msg = f"✅ 登録完了！\n- **{added_count}** 件を新規登録\n"
                if skipped_count > 0:
                    msg += f"- **{skipped_count}** 件は重複のためスキップされました"
                st.success(msg)

                # マスタ学習
                new_mappings = {}
                for _, r in edited_df.iterrows():
                    if r['category_1'] in ["支出", "収入"] and \
                       r['store'] and r['store'] not in master_dict and \
                       r['category_2'] not in ["未分類", "その他"]:
                        new_mappings[r['store']] = r['category_2']
                
                if new_mappings:
                    st.divider()
                    st.write("📚 新しい店名をマスタに登録しますか？")
                    st.json(new_mappings, expanded=False)
                    if st.button("マスタに保存"):
                        utils.update_category_master(new_mappings)
                        st.toast("マスタを更新しました")
                        master_dict.update(new_mappings)
            else:
                st.error(f"登録エラー: {added_count}")
    else:
        st.warning("有効なデータが見つかりませんでした。")