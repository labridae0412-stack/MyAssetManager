import streamlit as st
import pandas as pd
import utils
from datetime import date

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

# --- サイドバー：マスタ管理機能 ---
with st.sidebar:
    st.header("⚙️ マスタ管理")
    st.info("過去の登録データから、店名とカテゴリの組み合わせを学習させることができます。")
    if st.button("🔄 過去データからマスタを初期作成"):
        with st.spinner("データベースを解析中..."):
            count = utils.create_master_from_history()
            if count > 0:
                st.success(f"完了: {count} 件のキーワードをマスタに登録しました！")
            else:
                st.warning("新規に追加できるデータが見つかりませんでした。")

st.markdown("各金融機関のCSVを取り込み、**収支区分(Cat1)** と **費目(Cat2)** に分けて登録します。")
st.info("⚠️ スプレッドシートの **I列** に「残高」列が追加されていることを確認してください。")

# 1. 設定選択
col1, col2 = st.columns(2)
institution_name = col1.selectbox("🏦 金融機関を選択", list(utils.INSTITUTION_CONFIG.keys()))
selected_member_default = col2.selectbox("👤 デフォルトの対象者", utils.MEMBERS, index=0)

config = utils.INSTITUTION_CONFIG[institution_name]
target_sheet = config["sheet_name"]

# マスタ読み込み
master_dict = utils.load_category_master()

st.caption(f"保存先DB: **{target_sheet}** / 読み込み設定: {config['encoding']}")

# 2. ファイルアップロード
uploaded_file = st.file_uploader(f"{institution_name} のCSVをアップロード", type=["csv"])

if uploaded_file:
    try:
        df = pd.DataFrame()
        target_date = None

        # -----------------------------------------------------
        # 0. 読み込み処理 (通常 vs 特殊)
        # -----------------------------------------------------
        if "custom_loader" in config:
            # 特殊ローダー (証券など)
            if config["custom_loader"] == "rakuten_sec_balance":
                df = utils.load_rakuten_securities_csv(uploaded_file, config["encoding"])
                # ファイル名から日付抽出
                file_date = utils.extract_date_from_filename(uploaded_file.name)
                if file_date:
                    st.success(f"📅 ファイル名から日付を抽出しました: {file_date}")
                    target_date = file_date
                else:
                    target_date = st.date_input("日付が見つかりません。基準日を選択してください", date.today())
                
                if df is not None:
                    df["entry_date"] = target_date
        else:
            # 通常ローダー
            df = pd.read_csv(uploaded_file, encoding=config["encoding"])

        if df is None or df.empty:
            st.error("データを読み込めませんでした。")
        else:
            # データ整形用のリスト
            processed_rows = []

            # -----------------------------------------------------
            # パターンA: 楽天証券 (残高)
            # -----------------------------------------------------
            if "custom_loader" in config and config["custom_loader"] == "rakuten_sec_balance":
                # CSVの列名定義
                type_col = "種別"
                name_col = "銘柄" # または銘柄名
                val_col = "時価評価額[円]"

                if val_col in df.columns:
                    for _, row in df.iterrows():
                        # 評価額の整形
                        val_str = str(row.get(val_col, "0")).replace(',', '').replace('円', '')
                        try:
                            amount_val = int(float(val_str))
                        except:
                            amount_val = 0
                        
                        if amount_val > 0:
                            processed_rows.append({
                                "date": row["entry_date"],
                                "store": row.get(name_col, ""),
                                "category_1": "資産",
                                "category_2": row.get(type_col, "その他"),
                                "amount": amount_val,
                                "member": selected_member_default,
                                "institution": institution_name,
                                "balance": amount_val # 残高欄にも同じ値を入れる
                            })

            # -----------------------------------------------------
            # パターンB: クレジットカード (利用者列あり)
            # -----------------------------------------------------
            elif "member_col" in config:
                for index, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    if pd.isna(date_val): continue
                    
                    store_val = str(row[config["store_col"]]).strip()
                    
                    # 金額
                    amt_str = str(row[config["amount_col"]]).replace(',', '').replace('円', '')
                    try:
                        amount_val = int(float(amt_str))
                    except:
                        continue
                        
                    # 利用者列の処理 (CSV値を優先)
                    csv_member = str(row[config["member_col"]]).strip()
                    member_val = csv_member if csv_member else selected_member_default
                    
                    suggested_cat = utils.suggest_category(store_val, master_dict)

                    processed_rows.append({
                        "date": date_val,
                        "store": store_val,
                        "category_1": "支出",
                        "category_2": suggested_cat,
                        "amount": amount_val,
                        "member": member_val,
                        "institution": institution_name,
                        "balance": "" # クレカは残高なし
                    })

            # -----------------------------------------------------
            # パターンC: 通常の銀行 (2列 or 1列)
            # -----------------------------------------------------
            else:
                # 既存のロジック
                is_2col = ("expense_col" in config and "income_col" in config)
                
                for index, row in df.iterrows():
                    date_val = pd.to_datetime(row[config["date_col"]], errors='coerce').date()
                    store_val = str(row[config["store_col"]]).strip() if pd.notna(row[config["store_col"]]) else ""
                    if pd.isna(date_val): continue

                    # 残高取得
                    balance_val = None
                    if "balance_col" in config and config["balance_col"] in df.columns:
                        bal_str = str(row[config["balance_col"]]).replace(',', '').replace('円', '')
                        try:
                            balance_val = int(float(bal_str)) if bal_str and bal_str != 'nan' else None
                        except:
                            balance_val = None

                    # 金額・カテゴリ判定
                    amt = 0
                    cat1 = "支出"

                    if is_2col:
                        # 2列構成 (M銀行など)
                        e_str = str(row[config["expense_col"]]).replace(',', '').replace('円', '')
                        i_str = str(row[config["income_col"]]).replace(',', '').replace('円', '')
                        e_amt = int(float(e_str)) if e_str and e_str != 'nan' else 0
                        i_amt = int(float(i_str)) if i_str and i_str != 'nan' else 0
                        
                        if e_amt > 0: amt, cat1 = e_amt, "支出"
                        elif i_amt > 0: amt, cat1 = i_amt, "収入"
                    else:
                        # 1列構成
                        a_str = str(row[config["amount_col"]]).replace(',', '').replace('円', '')
                        raw_amt = int(float(a_str)) if a_str and a_str != 'nan' else 0
                        amt = abs(raw_amt)
                        cat1 = "支出" if raw_amt < 0 else "収入"
                    
                    if amt > 0:
                        suggested_cat = utils.suggest_category(store_val, master_dict)
                        # 収入で未分類なら「その他」へ
                        if cat1 == "収入" and suggested_cat == "未分類":
                            suggested_cat = "その他"

                        processed_rows.append({
                            "date": date_val,
                            "store": store_val,
                            "category_1": cat1,
                            "category_2": suggested_cat,
                            "amount": amt,
                            "member": selected_member_default,
                            "institution": institution_name,
                            "balance": balance_val
                        })

            # --- 結果表示と保存 ---
            if processed_rows:
                import_df = pd.DataFrame(processed_rows)
                
                st.write("### プレビュー (確認・編集)")
                if "custom_loader" not in config:
                    st.info("💡 店名からカテゴリを推論しました。「未分類」の箇所は手動で修正してください。")
                
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
                    hide_index=True,
                    key="editor"
                )
                
                if st.button(f"✅ {target_sheet} に登録実行"):
                    success, added_count, skipped_count = utils.save_bulk_to_google_sheets(edited_df, target_sheet, institution_name)
                    
                    if success:
                        st.balloons()
                        msg = f"登録完了！\n- **{added_count}** 件を新規登録しました。\n"
                        if skipped_count > 0:
                            msg += f"- **{skipped_count}** 件は重複のためスキップされました。"
                        
                        if added_count > 0:
                            st.success(msg)
                        else:
                            st.warning(msg)

                        # ------------------------------------------
                        # ★ マスタ学習ロジック (支出/収入のみ)
                        # ------------------------------------------
                        new_mappings = {}
                        for index, row in edited_df.iterrows():
                            # 資産データなどはマスタ学習の対象外とする
                            if row['category_1'] in ["支出", "収入"]:
                                store_name = row['store']
                                category = row['category_2']
                                if store_name and (store_name not in master_dict) and (category not in ["未分類", "その他"]):
                                    new_mappings[store_name] = category

                        if new_mappings:
                            st.divider()
                            st.subheader("🧠 マスタ学習の提案")
                            st.write("今回設定された以下の組み合わせを、カテゴリマスタに登録しますか？")
                            st.json(new_mappings, expanded=False)
                            
                            if st.button("💾 これらをマスタに保存する"):
                                count = utils.update_category_master(new_mappings)
                                st.toast(f"{count} 件の新しいルールを学習しました！", icon="🎓")
                                master_dict.update(new_mappings)
                    else:
                        st.error(f"登録失敗: {added_count}")
            else:
                st.warning("有効なデータが見つかりませんでした。")

    except Exception as e:
        st.error(f"読み込みエラー: {e}")