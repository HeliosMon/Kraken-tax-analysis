import streamlit as st
import pandas as pd
import io
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Kraken Tax FIFO Tool",
    page_icon="💰",
    layout="wide"
)

# --- CUSTOM CSS FOR STYLING ---
st.markdown("""
    <style>
    .main {
        background-color: #f5f7f9;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.title("Settings & Help")
    st.info("""
    **How to use:**
    1. Export your **Ledger** (not Trades) from Kraken.
    2. Upload the `.csv` file here.
    3. Review the calculated FIFO gains.
    4. Download the Excel for your records.
    """)
    st.divider()
    st.warning("⚠️ **Privacy:** Data is processed in memory and never stored on this server.")

# --- CORE LOGIC ---
def calculate_tax_logic(df):
    try:
        # Data Cleaning
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values(['time', 'refid'])
        
        inventory = {}
        tax_data = []
        EPSILON = 1e-9 

        # 1. Trade-Mapping for EUR-values
        trades = {}
        for refid, group in df.groupby('refid'):
            eur_rows = group[group['asset'].isin(['ZEUR', 'EUR'])]
            if not eur_rows.empty:
                trades[refid] = {
                    'eur_total': abs(eur_rows['amount'].sum()),
                    'fee_total': group['fee'].sum()
                }

        # 2. Ledger Processing
        for idx, row in df.iterrows():
            asset = row['asset']
            if asset in ['ZEUR', 'EUR', 'KFEE']: continue
            
            # Clean asset name
            asset = asset.replace('ZEUR', '').replace('EUR', '').replace('X', '', 1) if asset.startswith('X') else asset
            raw_amount, fee, date, refid = float(row['amount']), float(row['fee']), row['time'], row['refid']

            # BUY / INFLOW
            if raw_amount > 0:
                eur_paid = trades.get(refid, {}).get('eur_total', 0)
                inventory.setdefault(asset, []).append({
                    'amount': raw_amount - fee,
                    'pure_price_eur': eur_paid, 
                    'buy_fee': fee, 
                    'date': date
                })
                
            # SELL / OUTFLOW
            elif raw_amount < 0:
                if asset not in inventory or not inventory[asset]: continue
                
                abs_sell_amount = abs(raw_amount)
                eur_received = trades.get(refid, {}).get('eur_total', 0)
                sell_fee = trades.get(refid, {}).get('fee_total', 0)
                sell_vol_remaining = abs_sell_amount
                
                while sell_vol_remaining > EPSILON and inventory[asset]:
                    first_buy = inventory[asset][0]
                    days_held = (date - first_buy['date']).days
                    
                    amount_to_process = min(sell_vol_remaining, first_buy['amount'])
                    
                    # Only calculate tax for assets held <= 365 days (German Tax Logic)
                    if days_held <= 365:
                        # Proportional calculations
                        v_preis = (eur_received / abs_sell_amount) * amount_to_process
                        k_preis = (first_buy['pure_price_eur'] / (first_buy['amount'] + (0 if first_buy['amount'] > 0 else 1e-12))) * amount_to_process
                        nk_anschauung = (first_buy['buy_fee'] / (first_buy['amount'] + (0 if first_buy['amount'] > 0 else 1e-12))) * amount_to_process
                        vk_kosten = (sell_fee / abs_sell_amount) * amount_to_process

                        tax_data.append({
                            'Asset': asset,
                            'Verkaufsdatum': date.strftime('%d.%m.%Y'),
                            'Anschaffungsdatum': first_buy['date'].strftime('%d.%m.%Y'),
                            'Haltedauer (Tage)': days_held,
                            'Menge': round(amount_to_process, 8),
                            'Erlös (EUR)': round(v_preis, 2),
                            'Anschaffungskosten (EUR)': round(k_preis + nk_anschauung, 2),
                            'Veräußerungskosten (EUR)': round(vk_kosten, 2),
                            'Gewinn/Verlust': round(v_preis - (k_preis + nk_anschauung) - vk_kosten, 2)
                        })

                    # FIFO update
                    sell_vol_remaining -= amount_to_process
                    first_buy['amount'] -= amount_to_process
                    if first_buy['amount'] < EPSILON:
                        inventory[asset].pop(0)

        return pd.DataFrame(tax_data), None
    except Exception as e:
        return None, str(e)

# --- MAIN UI ---
st.title("⚖️ Crypto Tax Calculator (FIFO)")
st.subheader("Generate your tax report from Kraken Ledger files")

uploaded_file = st.file_uploader("Drop your kraken_ledger.csv here", type=["csv"])

if uploaded_file:
    # Read the CSV
    try:
        df_input = pd.read_csv(uploaded_file)
        
        # Basic validation
        required_cols = ['time', 'asset', 'amount', 'fee', 'refid']
        if not all(col in df_input.columns for col in required_cols):
            st.error("❌ The uploaded file is missing required columns. Please use the original Kraken Ledger export.")
        else:
            with st.spinner('Calculating FIFO stacks...'):
                result_df, error = calculate_tax_logic(df_input)
            
            if error:
                st.error(f"❌ Error during calculation: {error}")
            elif result_df.empty:
                st.info("ℹ️ No taxable sales found (all assets held > 365 days or no sales recorded).")
            else:
                # Results UI
                st.success("✅ Calculation Complete")
                
                col1, col2 = st.columns(2)
                total_profit = result_df['Gewinn/Verlust'].sum()
                
                with col1:
                    st.metric("Total Taxable Profit/Loss", f"{total_profit:,.2f} €")
                
                st.divider()
                st.dataframe(result_df, use_container_width=True)

                # Excel Download
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    result_df.to_excel(writer, index=False, sheet_name='FIFO_Tax_Report')
                
                st.download_button(
                    label="📥 Download Report as Excel",
                    data=buffer.getvalue(),
                    file_name=f"Kraken_Tax_Report_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"❌ Failed to parse CSV: {e}")
else:
    st.write("---")
    st.info("Please upload a file to begin.")
