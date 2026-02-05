import os
import time
from datetime import datetime
import json
import glob
import gspread
import logging
from google.oauth2.service_account import Credentials

operation_count = 0
def operation_check():
    global operation_count
    operation_count += 1
    if operation_count > 30:
        operation_count = 0
        print("wait for the google auth limitation...")
        time.sleep(101)

def export(test_name: str, sheet_name: str):
    print('sheet_name', sheet_name)
    # 1. Google Sheets 權限設置（將 service_account.json 放在腳本同目錄下）
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    SERVICE_ACCOUNT_FILE = 'config/service_account.json'  # 換成你的 json key 路徑
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(credentials)

    # 2. 打開 Google Sheet
    with open('sheet_id_list.json', 'r', encoding='utf8') as f:
        sheet_id_map = json.load(f)
    if sheet_name not in sheet_id_map:
        raise ValueError(f'sheet_name "{sheet_name}" not found in sheet_id_list.json')
    sheet_value = sheet_id_map[sheet_name]
    if isinstance(sheet_value, str) and '/d/' in sheet_value:
        SHEET_ID = sheet_value.split('/d/', 1)[1].split('/', 1)[0]
    else:
        SHEET_ID = sheet_value
    print('SHEET_ID', SHEET_ID)

    sheet = gc.open_by_key(SHEET_ID)
    now_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    if test_name in [ws.title for ws in sheet.worksheets()]:
        logging.warning(f'worksheet {test_name} exists, clear content')
        worksheet = sheet.worksheet(test_name)
        # clear existing content
        worksheet.clear()
        operation_check()
    else:
        worksheet = sheet.add_worksheet(title=test_name, rows="100", cols="50")

    # 3. 收集所有 result.json 檔案
    files = glob.glob(f'./results/{test_name}/*/*/result.json')

    # 4. 整理並推送資料
    header = None
    rows = []


    for file_path in files:
        with open(file_path, 'r', encoding='utf8') as f:
            data = json.load(f)
        
        if 'remark' not in data:
            data['remark'] = ''
        if 'seed' not in data:
            data['seed'] = 'random'

        # 加上 benchmark 及日期時間（目錄條件）
        parts = file_path.split(os.sep)
        # 比如 ['./result', '{test_name}', '{benchmark}', '{日期時間}', 'result.json']
        if len(parts) >= 5:
            benchmark = parts[3]
            date_time = parts[4]
        else:
            benchmark, date_time = '', ''
        
        # 展開成一列
        if header is None:
            header = ['date_time'] + list(data.keys())
            worksheet.clear()
            operation_check()

            worksheet.append_row(header)
            operation_check()

        row = [date_time] + [data.get(k, '') for k in header[1:]]
        rows.append(row)

    # 批量寫入
    for row in rows:
        worksheet.append_row(row)
        operation_check()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # 讀取 sheet_id_list.json，讓使用者選擇輸出目的地
    with open('sheet_id_list.json', 'r', encoding='utf8') as f:
        sheet_id_map = json.load(f)
    sheet_names = list(sheet_id_map.keys())
    print('Available sheet names:')
    for name in sheet_names:
        print(f'- {name}')
    selected_sheet = input('Enter the sheet name to export: ').strip()

    # 找到 ./result 下面一層資料夾有哪些，列出選項讓使用者輸入
    folders = next(os.walk('./results'))[1]
    print('Available test names:')
    for f in folders:
        print(f'- {f}')
    selected_folder = input('Enter the test name to export: ').strip()
    
    operation_check()
    if selected_sheet not in sheet_names:
        print(f'Sheet name "{selected_sheet}" not found in sheet_id_list.json.')
    elif selected_folder in folders:
        try:
            export(selected_folder, selected_sheet)
            print("export completed.")
        except Exception as e:
            print("export failed.", e)
    else:
        print(f'Test name "{selected_folder}" not found in ./results.')
