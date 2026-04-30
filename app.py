import streamlit as st
import pandas as pd
import io
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Crypto Tax FIFO Tool",
    page_icon="⚖️",
    layout="wide"
)

# --- SIDEBAR CONTROLS ---
with st.sidebar:
    st.title("⚙️ Tax Parameters")
    selected_year = st.selectbox(
        "Select Tax Year",
        options=list(range(datetime.now().year, 2010, -1)),
        index=0
    )
    months_threshold = st.slider(
        "Tax-Free Holding Period (Months)",
        min_value=0, max_value=120, value=12
    )
    days_threshold = months_threshold * 30.44 

    st.divider()
    st.info("💡 **Tip:** This tool uses the 'Absolute Proportional' method to ensure the Cost Basis is 100% accurate down to the cent.")

# --- CORE LOGIC ---
def calculate_tax_logic(df, target_year, hold_days):
    try:
        # Ensure time is sorted to the second
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values(by=['time', 'refid']).reset_index(drop=True)
        
        inventory = {}
        tax_data = []
        EPSILON = 1e-10 

        # 1. Map EUR totals to RefIDs (Kraken specific)
        trades = {}
        for refid, group in df.groupby('refid'):
            eur_rows = group[group['asset'].isin(['ZEUR', 'EUR'])]
            if not eur_rows.empty:
                trades[refid] = {
                    'eur_total': abs(eur_rows['amount'].sum()),
                    'fee_total': group['fee'].sum()
                }

        # 2. FIFO Processing
        for idx, row in df.iterrows():
            asset = row['asset']
            if asset in ['ZEUR', 'EUR', 'KFEE']: continue
            
            asset = asset.replace('ZEUR', '').replace('EUR', '').replace('X', '', 1) if asset.startswith('X') else asset
            raw_amount = float(row['amount'])
            fee = float(row['fee'])
            date = row['time']
            refid = row['refid']

            # --- INFLOW (BUY) ---
            if raw_amount > 0:
                eur_paid = trades.get(refid, {}).get('eur_total', 0)
                # We store the total amount bought and the total cost for that specific "pot"
                inventory.setdefault(asset, []).append({
                    'original_amount': raw_amount - fee,
                    'remaining_amount': raw_amount - fee,
                    'total_cost_basis': eur_paid, # The full price paid for this pot
                    'buy_fee': fee, 
                    'date': date
                })
                
            # --- OUTFLOW (SELL) ---
            elif raw_amount < 0:
                if asset not in inventory or not inventory[asset]: continue
                
                abs_sell_total = abs(raw_amount)
                eur_received_total = trades.get(refid, {}).get('eur_total', 0)
                sell_fee_total = trades.get(refid, {}).get('fee_total', 0)
                sell_vol_remaining = abs_sell_total
                
                while sell_vol_remaining > EPSILON and inventory[asset]:
                    pot = inventory[asset][0] # Get the oldest pot
                    amount_to_take = min(sell_vol_remaining, pot['remaining_amount'])
                    
                    # Calculate the fraction of the pot we are taking
                    # Fraction = amount_we_take / total_amount_that_was_in_this_pot
                    fraction_of_pot = amount_to_take / pot['original_amount']
                    
                    # Calculation for this specific slice of the sale
                    if date.year == target_year:
                        # Proceeds for this slice
                        slice_proceeds = (eur_received_total / abs_sell_total) * amount_to_take
                        # Cost basis for this slice (Proportional to the original pot cost)
                        slice_cost_basis = pot['total_cost_basis'] * fraction_of_pot
                        # Proportional fees
                        slice_sell_fee = (sell_fee_total / abs_sell_total) * amount_to_take
                        
                        days_held = (date - pot['date']).days
                        gain_loss = slice_proceeds - slice_cost_basis - slice_sell_fee
                        is_taxable = days_held <= hold_days

                        tax_data.append({
                            'Asset': asset,
                            'Sell Date': date,
                            'Buy Date': pot['date'],
                            'Holding Period (Days)': days_held,
                            'Amount': round(amount_to_take, 8),
                            'Proceeds (EUR)': round(slice_proceeds, 2),
                            'Cost Basis (EUR)': round(slice_cost_basis, 2),
                            'Selling Fees (EUR)': round(slice_sell_fee, 2),
                            'Gain/Loss (EUR)': round(gain_loss, 2),
                            'Taxable': "Yes" if is_taxable else "No"
                        })

                    # Subtract from FIFO pot
                    sell_vol_remaining -= amount_to_take
                    pot['remaining_amount'] -= amount_to_take
                    
                    # Remove pot if empty
                    if pot['remaining_amount'] < EPSILON:
                        inventory[asset].pop(0)

        return pd.DataFrame(tax_data), None
    except Exception as e:
        return None, str(e)

# --- MAIN UI ---
st.title("⚖️ Crypto Tax Calculator (Accurate FIFO)")

uploaded_file = st.file_uploader("Upload Kraken Ledger CSV", type=["csv"])

if uploaded_file:
    try:
        df_input = pd.read_csv(uploaded_file)
        result_df, error = calculate_tax_logic(df_input, selected_year, days_threshold)
        
        if error:
            st.error(f"Error: {error}")
        elif result_df is not None and not result_df.empty:
            # Metrics
            total_gains = result_df['Gain/Loss (EUR)'].sum()
            taxable_gains = result_df[result_df['Taxable'] == "Yes"]['Gain/Loss (EUR)'].sum()
            
            m1, m2 = st.columns(2)
            m1.metric("Total Realized Gain/Loss", f"{total_gains:,.2f} €")
            m2.metric("Total Taxable Gain/Loss", f"{taxable_gains:,.2f} €")
            
            st.dataframe(result_df.sort_values('Sell Date', ascending=False), use_container_width=True)

            # Export
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                result_df.to_excel(writer, index=False, sheet_name='FIFO_Report')
            st.download_button("📥 Download Excel Report", buffer.getvalue(), f"Tax_Report_{selected_year}.xlsx")
    except Exception as e:
        st.error(f"File Error: {e}")
