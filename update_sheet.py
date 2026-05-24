import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import zipfile
import io
from datetime import datetime, timedelta
import os
import json

# 1. Credentials Setup
creds_json = os.environ.get('GCP_CREDENTIALS')

if not creds_json:
    print("CRITICAL: GCP_CREDENTIALS secret missing!")
    exit(1)

creds_dict = json.loads(creds_json)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Google Sheet ID
spreadsheet_id = "1D4QckE_FCcBjzVn3ge7G4Xvx95i4fZRYlXRAllNzg9o"

worksheet = client.open_by_key(spreadsheet_id).worksheet("ETF Stocks")

# 2. NSE Data Fetcher (ETF LOGIC)

def fetch_bhavcopy_for_date(date_obj):

    date_str = date_obj.strftime("%Y%m%d")

    url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"

    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    try:

        response = requests.get(url, headers=headers, timeout=20)

        if response.status_code == 200:

            with zipfile.ZipFile(io.BytesIO(response.content)) as z:

                csv_filename = z.namelist()[0]

                with z.open(csv_filename) as f:

                    df = pd.read_csv(f)

                    df.columns = [c.strip() for c in df.columns]

                    sym_col = next((c for c in ['TckrSymb', 'SYMBOL'] if c in df.columns), None)

                    close_col = next((c for c in ['ClsPric', 'CLOSE'] if c in df.columns), None)

                    series_col = next((c for c in ['SctySrs', 'SERIES'] if c in df.columns), None)

                    turnover_col = next(
                        (c for c in ['TtlTrfVal', 'TtlTrdVal', 'TURNOVER_LACS', 'TURNOVER'] if c in df.columns),
                        None
                    )

                    if not all([sym_col, close_col, turnover_col]):
                        return None

                    # केवल EQ Series
                    if series_col:
                        df = df[df[series_col].astype(str).str.strip() == 'EQ']

                    # ETF FILTER
                    etf_keywords = 'ETF|BEES|GOLD|LIQUID|NIFTY|SILVER'

                    df_etf = df[
                        df[sym_col].astype(str).str.contains(
                            etf_keywords,
                            case=False,
                            na=False
                        )
                    ]

                    # Numeric turnover
                    df_etf[turnover_col] = pd.to_numeric(
                        df_etf[turnover_col],
                        errors='coerce'
                    )

                    df_etf = df_etf.dropna(subset=[turnover_col])

                    # Top ETFs by turnover
                    df_top = df_etf.sort_values(
                        by=turnover_col,
                        ascending=False
                    ).head(250)

                    return df_top[[sym_col, turnover_col, close_col]].values.tolist()

        return None

    except Exception as e:
        print("ERROR:", str(e))
        return None

# 3. Execution Logic

date = datetime.now()

data_to_insert = None
fetched_date_str = ""

for i in range(7):

    test_date = date - timedelta(days=i)

    if test_date.weekday() >= 5:
        continue

    data_to_insert = fetch_bhavcopy_for_date(test_date)

    if data_to_insert:

        fetched_date_str = test_date.strftime('%d-%b-%Y')

        break

# 4. Update Google Sheet

if data_to_insert:

    try:

        worksheet.batch_clear(['A2:C251'])

        worksheet.update('A2', data_to_insert)

        ist_now = (
            datetime.utcnow() + timedelta(hours=5, minutes=30)
        ).strftime('%d-%b %H:%M')

        status_msg = (
            f"ETF Data Date: {fetched_date_str} | "
            f"Last Update: {ist_now} (IST)"
        )

        worksheet.update('K2', [[status_msg]])

        print(f"SUCCESS: ETF Sheet Updated for {fetched_date_str}")

    except Exception as e:

        print(f"Google Sheet Error: {str(e)}")

else:

    print("FAILED: पिछले 7 दिनों में ETF फाइल नहीं मिली।")
