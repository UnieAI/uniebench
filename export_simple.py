import os
import time
from datetime import datetime
import json
import glob
import csv
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

def _collect_rows(test_name: str):
    # 1. 收集所有 result.json 檔案
    if test_name.endswith('.json'):
        files = [test_name]
    else:
        files = glob.glob(f'./results/{test_name}/*/*/result.json')

    # 2. 整理資料
    header = None
    rows = []
    for file_path in files:
        with open(file_path, 'r', encoding='utf8') as f:
            alldata = json.load(f)
            if not isinstance(alldata, list):
                alldata = [alldata]

        for data in alldata:
            # if 'remark' not in data:
            #     data['remark'] = ''
            # if 'seed' not in data:
            #     data['seed'] = 'random'

            parts = file_path.split(os.sep)
            if len(parts) >= 5:
                date_time = parts[4]
            else:
                date_time = ''

            if header is None:
                data_keys = list(data.keys())
                if 'engine' in data_keys:
                    data_keys = ['engine'] + [k for k in data_keys if k != 'engine']
                    header = data_keys[:1] + ['date_time'] + data_keys[1:]
                else:
                    header = ['date_time'] + data_keys

            row = [date_time if k == 'date_time' else data.get(k, '') for k in header]
            rows.append(row)

    if header is None:
        header = ['date_time']

    return header, rows

import glob
def benchmark_post_processing(path):
    dist_folder = './results'
    os.makedirs(dist_folder, exist_ok=True)
    
    # result.json
    sources = glob.glob(f'{path}/*.json')
    all_result = []
    for source in sources:
        with open(source, 'r') as fr:
            data = json.load(fr)

        completed = data.get('completed', 0)
        if completed <= 0:
            logging.warning(
                'result has no completed requests; token averages set to 0: %s',
                source,
            )
        
        result = {
            "platform": 'Pro6000',
            "engine": source,
            "benchmark": 'inferencemax-h100',

            "request_count": completed,
            "interval": data['duration'] * 1000, # second to ms
            "concurrency": data['max_concurrency'],
            "model_name": data['tokenizer_id'],
            "input_tokens": data['total_input_tokens'] / completed if completed else 0,
            "output_tokens": data['total_output_tokens'] / completed if completed else 0,

            "request_throughput": data['request_throughput'],
            "output_token_throughput": data['output_throughput'],

            "request_latency.avg": data['mean_e2el_ms'],
            "request_latency.median": data['median_e2el_ms'],
            "request_latency.std": data['std_e2el_ms'],
            "request_latency.p99": data['p99_e2el_ms'],

            "time_to_first_token.avg": data['mean_ttft_ms'],
            "time_to_first_token.median": data['median_ttft_ms'],
            "time_to_first_token.std": data['std_ttft_ms'],
            "time_to_first_token.p99": data['p99_ttft_ms'],

            "inter_token_latency.avg": data['mean_itl_ms'],
            "inter_token_latency.median": data['median_itl_ms'],
            "inter_token_latency.std": data['std_itl_ms'],
            "inter_token_latency.p99": data['p99_itl_ms'],
        }
        all_result.append(result)
    
    try:
        os.mkdir('./export')
    except:
        pass
    dist = './export/result.json'
    with open(dist, 'w') as fw:
        json.dump(all_result, fw, indent=4)

    # shutil.copy(source, dist_folder)
    return dist


def _export_to_csv_fallback(test_name: str, worksheet_name: str, header, rows):
    # os.makedirs('bench_export', exist_ok=True)
    name = input('csv name: > ')
    now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = worksheet_name or os.path.basename(test_name)
    if base_name.endswith('.json'):
        base_name = os.path.splitext(base_name)[0]
    safe_name = base_name.replace(os.sep, '_').replace(' ', '_')
    output_path = f'./export/{name}_{now_str}.csv'

    with open(output_path, 'w', encoding='utf8', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)
        writer.writerows(rows)

    logging.warning(
        'service_account.json not found; exported to CSV fallback: %s',
        output_path,
    )
    print(f'CSV fallback output: {output_path}')

def export(test_name: str, sheet_name: str, worksheet_name = None):
    worksheet_name = worksheet_name or test_name
    print('sheet_name', sheet_name)
    header, rows = _collect_rows(test_name)

    # 1. Google Sheets 權限設置（將 service_account.json 放在腳本同目錄下）
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    SERVICE_ACCOUNT_FILE = 'config/service_account.json'  # 換成你的 json key 路徑
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        _export_to_csv_fallback(test_name, worksheet_name, header, rows)
        return
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

    if worksheet_name in [ws.title for ws in sheet.worksheets()]:
        logging.warning(f'worksheet {worksheet_name} exists, clear content')
        worksheet = sheet.worksheet(worksheet_name)
        # clear existing content
        worksheet.clear()
        operation_check()
    else:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows="100", cols="50")

    worksheet.append_row(header)
    operation_check()

    # 批量寫入
    for row in rows:
        worksheet.append_row(row)
        operation_check()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    path = input('path: > ')
    path = benchmark_post_processing(path)
    path = export(path, path)

    # # 讀取 sheet_id_list.json，讓使用者選擇輸出目的地
    # with open('sheet_id_list.json', 'r', encoding='utf8') as f:
    #     sheet_id_map = json.load(f)
    # sheet_names = list(sheet_id_map.keys())
    # print('Available sheet names:')
    # for name in sheet_names:
    #     print(f'- {name}')
    # selected_sheet = input('Enter the sheet name to export: ').strip()

    # # 找到 ./result 下面一層資料夾有哪些，列出選項讓使用者輸入
    # try:
    #     folders = next(os.walk('./results'))[1]
    # except:
    #     folders = []
        
    # print('Available test names:')
    # for f in folders:
    #     print(f'- {f}')
    # selected_folder = input('Enter the test name or full json path to export: ').strip()
    # worksheet_name = None
    # if selected_folder not in folders:
    #     worksheet_name = input("Enter new worksheet name: ")

    # operation_check()
    # if selected_sheet not in sheet_names:
    #     print(f'Sheet name "{selected_sheet}" not found in sheet_id_list.json.')
    # else:
    #     try:
    #         export(selected_folder, selected_sheet, worksheet_name)
    #         print("export completed.")
    #     except Exception as e:
    #         print("export failed.", e)
