# -*- coding: utf-8 -*-
"""
App A – Tokyu Departure Board WebApp
FULL SOURCE rev-2025-05-18  (★ CSV 対応版)

機能
──────────────────────────────────────────
▪ 発車案内   (CSV ➜ walk/run advice)
▪ 天気       Tsukumijima Weather JSON FULL（3日分）
▪ ニュース   NHK RSS + Google News
▪ 運行情報   Tokyu scrape + ODPT → 各社平常 or 異常のみ（日本語路線名＋ロゴ付き）
──────────────────────────────────────────
"""

from __future__ import annotations
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import html
import requests
import pandas as pd
import feedparser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template

# ──────────────────────────────────────────
#  ディレクトリ・ファイルパス定義
# ──────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent              # timetable-app/
DATA_DIR   = BASE_DIR / "timetable_data"                  # ★ 時刻表置き場 (CSV/Excel)
STATIC_DIR = BASE_DIR / "static"                          # 画像・CSS・JS

# バス Excel ファイル
bus_timetable_file  = DATA_DIR / "timetablebus.xlsx"
bus_timetable_file2 = DATA_DIR / "timetablebus2.xlsx"
bus_timetable_file3 = DATA_DIR / "timetablebus3.xlsx"

# Flask アプリ
app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder="templates")

# ──────────────────────────────────────────
#  ユーティリティ : 電車 (CSV)
# ──────────────────────────────────────────
# _DEST_MAP は ROUTES に移行するため削除

_DAY_MAP = {   # datetime.weekday() ➜ ファイル名用タグ
    0: "weekday", 1: "weekday", 2: "weekday", 3: "weekday", 4: "weekday",
    5: "holiday",  # 土曜日も休日ダイヤを参照するように変更
    6: "holiday",
}

def fetch_train_schedule(line_code: str, dest_tag: str) -> list[dict[str, str]]:
    """
    指定された路線の電車時刻表を CSV から読み込んで
    {"time": "HH:MM", "type": "種別", "dest": "行き先"} の辞書のリストを返す
      line_code: "OM", "TY", "MG", "BL" など
      dest_tag : "Ooimachi", "Mizonokuchi", "Shibuya", "Yokohama", "Meguro", "Hiyoshi", "Azamino", "Shonandai" など
    """
    # 1) 対象 CSV ファイル決定
    today_tag = _DAY_MAP[datetime.now().weekday()]
    csv_path  = DATA_DIR / f"timetable_{line_code}_{today_tag}_{dest_tag}.csv"

    # ブルーライン用のデバッグ出力を追加
    if line_code == "BL":
        print(f"[DEBUG] 読み込み試行: {csv_path} (存在: {csv_path.exists()})")

    if not csv_path.exists():
        print(f"[WARN] CSV not found: {csv_path}")
        return []

    # 2) CSV 読込
    df = None
    try:
        # header=0 を明示し、1行目をヘッダーとして扱う
        # keep_default_na=False で、空欄を空文字列として読み込む
        # dtype=str を追加して、すべての列を文字列として読み込むことで、予期せぬ型変換を防ぐ
        df = pd.read_csv(csv_path, encoding="utf-8", header=0, keep_default_na=False, dtype=str)
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(csv_path, encoding="cp932", header=0, keep_default_na=False, dtype=str)
        except Exception as e_cp932:
            print(f"[ERROR] CSV read error (cp932): {csv_path} - {e_cp932}")
            return []
    except Exception as e:
        print(f"[ERROR] CSV read error (utf-8): {csv_path} - {e}")
        return []

    if df is None or df.empty:
        # print(f"[INFO] CSV is empty or failed to load: {csv_path}") # 既に読み込み失敗時にエラーが出るため、重複を避ける
        return []

    # 3) 時刻・種別・行き先抽出
    out: list[dict[str, str]] = []
    
    num_columns = len(df.columns)
    if num_columns == 0:
        print(f"[WARN] CSV has no columns: {csv_path}")
        return []

    # デバッグ用に列名を出力したい場合は以下のコメントを解除
    # print(f"[DEBUG] CSV Columns for {csv_path}: {df.columns.tolist()}") 

    for index, row in df.iterrows():
        try:
            time_str = str(row.iloc[0]).strip()
            if not time_str:
                # print(f"[DEBUG] Skipping row due to empty time: {row.to_list()} in {csv_path}")
                continue
            
            try:
                # "H:MM" または "HH:MM" 形式をパースし、"HH:MM" に正規化
                parts = time_str.split(':')
                if len(parts) == 2:
                    h, m = int(parts[0]), int(parts[1])
                    formatted_time = f"{h:02d}:{m:02d}"
                    datetime.strptime(formatted_time, "%H:%M") # 正当性チェック
                else:
                    # print(f"[DEBUG] Skipping row due to invalid time format '{time_str}': {row.to_list()} in {csv_path}")
                    continue
            except ValueError:
                # print(f"[DEBUG] Skipping row due to invalid time format '{time_str}': {row.to_list()} in {csv_path}")
                continue

            train_type = ""
            if num_columns > 1:
                train_type = str(row.iloc[1]).strip()
            
            destination = ""
            if num_columns > 2:
                destination = str(row.iloc[2]).strip()
            
            if train_type.lower() in ["nan", "na", "<na>", "-", "ー"]: train_type = ""
            if destination.lower() in ["nan", "na", "<na>", "-", "ー"]: destination = ""

            out.append({
                "time": formatted_time,
                "type": train_type,
                "dest": destination
            })
        except (ValueError, TypeError) as e_parse:
            # print(f"[DEBUG] Skipping row due to parse error ({e_parse}): {row.to_list()} in {csv_path}")
            pass
        except IndexError as e_index: 
            # print(f"[DEBUG] Skipping row due to IndexError ({e_index}): {row.to_list()} in {csv_path}")
            pass
            
    if not out and not df.empty: # CSVにデータ行はあるが、有効な時刻情報が抽出できなかった場合
        print(f"[INFO] No valid schedule entries extracted from {csv_path}. Please check CSV format (time in 1st col, etc.) and content.")
        # さらに詳細なデバッグが必要な場合、以下のコメントを解除
        # print(f"[DEBUG] First 5 rows of CSV {csv_path} that might have issues:\n{df.head().to_string()}")

    return sorted(out, key=lambda x: x["time"])


# ──────────────────────────────────────────
#  ユーティリティ : バス (従来どおり Excel)
# ──────────────────────────────────────────
def fetch_bus_schedule(sheet: str, col: str, path: Path) -> list[str]:
    """バス時刻表（行方向：時、列方向：分）を HH:MM リストで返す"""
    df = pd.read_excel(path, sheet_name=sheet)
    if "時" not in df.columns:
        df.rename(columns={df.columns[0]: "時"}, inplace=True)
    if col not in df.columns:
        col = df.columns[1]
    out = []
    for _, row in df.iterrows():
        h = str(row["時"]).strip()
        if not h.isdigit() or pd.isna(row[col]):
            continue
        for m in str(row[col]).split():
            if m.isdigit():
                out.append(f"{h.zfill(2)}:{m.zfill(2)}")
    return out


def sheet_name(kind: str, key: str | None = None) -> str:
    """曜日判定してシート名を返すヘルパ（バス用のみ）"""
    wd = datetime.now().weekday()
    if kind in ("bus", "bus_2"):
        return f"{'平日' if wd < 5 else '土休日'}_{key}"
    if kind == "bus_3":
        if wd < 5:
            return f"平日_{key}"
        if wd == 5:
            return f"土曜_{key}"
        return f"日休日_{key}"
    raise ValueError("kind error")


def remaining(dep_time: str) -> timedelta:
    """HH:MM 形式 ➜ 出発までの残り time delta"""
    now = datetime.now()
    dep = datetime.strptime(dep_time, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    if dep < now:
        dep += timedelta(days=1)
    return dep - now


def fetch_bus_schedule_csv(bus_type: str, dest_tag: str) -> list[dict[str, str]]:
    """
    バス時刻表をCSVから読み込んで電車と同じ形式で返す
    {"time": "HH:MM", "type": "", "dest": "行き先"} の辞書のリスト
    """
    # 曜日に応じたファイル選択
    wd = datetime.now().weekday()
    day_tag = "weekday"
    if wd == 5:  # 土曜日
        day_tag = "saturday"
    elif wd == 6:  # 日曜日
        day_tag = "holiday"
    
    # CSVファイルパス
    csv_path = DATA_DIR / f"timetable_BUS_{day_tag}_{dest_tag}.csv"
    
    print(f"[DEBUG] バスCSV読み込み試行: {csv_path} (存在: {csv_path.exists()})")
    
    if not csv_path.exists():
        print(f"[WARN] バスCSV not found: {csv_path}")
        return []
    
    # CSV読込
    df = None
    try:
        df = pd.read_csv(csv_path, encoding="utf-8", header=0, keep_default_na=False, dtype=str)
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(csv_path, encoding="cp932", header=0, keep_default_na=False, dtype=str)
        except Exception as e_cp932:
            print(f"[ERROR] バスCSV read error (cp932): {csv_path} - {e_cp932}")
            return []
    except Exception as e:
        print(f"[ERROR] バスCSV read error (utf-8): {csv_path} - {e}")
        return []
    
    if df is None or df.empty:
        return []
    
    # 時刻・行き先抽出
    out = []
    for _, row in df.iterrows():
        try:
            time_str = str(row.iloc[0]).strip()
            if not time_str:
                continue
            
            # 時刻のフォーマット
            try:
                parts = time_str.split(':')
                if len(parts) == 2:
                    h, m = int(parts[0]), int(parts[1])
                    formatted_time = f"{h:02d}:{m:02d}"
                    datetime.strptime(formatted_time, "%H:%M")  # 正当性チェック
                else:
                    continue
            except ValueError:
                continue
            
            # 行き先
            destination = ""
            if len(df.columns) > 1:
                destination = str(row.iloc[1]).strip()
            
            if destination.lower() in ["nan", "na", "<na>", "-", "ー"]:
                destination = ""
            
            out.append({
                "time": formatted_time,
                "type": "",  # バスの種別は空
                "dest": destination
            })
        except (ValueError, TypeError, IndexError):
            pass
    
    return sorted(out, key=lambda x: x["time"])


# ──────────────────────────────────────────
#  発車案内ルート定義
# ──────────────────────────────────────────
ROUTES = [
    dict(
        label="東急大井町線　尾山台駅",
        type="train",
        line_code="OM",
        directions=[
            dict(column="大井町方面", dest_tag="Ooimachi"),
            dict(column="溝の口方面", dest_tag="Mizonokuchi"),
        ],
        max=3,
        walk=14,
        run=10,
    ),
    dict(
        label="東急東横線　田園調布駅", # ラベル変更
        type="train",
        line_code="TY",
        directions=[
            dict(column="渋谷方面", dest_tag="Shibuya"),
            dict(column="横浜方面", dest_tag="Yokohama"),
        ],
        max=3,
        walk=30, # 所要時間変更
        run=25,  # 所要時間変更
    ),
    dict(
        label="東急目黒線　田園調布駅", # ラベル変更
        type="train",
        line_code="MG",
        directions=[
            dict(column="目黒方面", dest_tag="Meguro"),
            dict(column="日吉方面", dest_tag="Hiyoshi"),
        ],
        max=3,
        walk=30, # 所要時間変更
        run=25,  # 所要時間変更
    ),
    # --- ここから追加 ---
    dict(
        label="横浜市営地下鉄ブルーライン 中川駅",
        type="train",
        line_code="BL", # ブルーラインの路線コード (仮)
        directions=[
            dict(column="あざみ野方面", dest_tag="Azamino"),
            dict(column="湘南台方面", dest_tag="Shonandai"),
        ],
        max=3, # 表示件数 (他に合わせて3件)
        walk=15,
        run=10,
    ),
    # --- ここまで追加 ---
    dict(
        label="玉11　東京都市大学南入口",
        type="bus",
        file=bus_timetable_file,
        directions=[
            dict(column="多摩川駅方面", sheet_direction="多摩川"),
            dict(column="二子玉川駅方面", sheet_direction="二子玉川"),
        ],
        max=2,
        walk=7,
        run=5,
    ),
    dict(
        label="園02　東京都市大学北入口",
        type="bus_3",
        file=bus_timetable_file3,
        directions=[
            dict(column="千歳船橋駅方面", sheet_direction="千歳船橋"),
            dict(column="田園調布方面", sheet_direction="田園調布"),
        ],
        max=2,
        walk=7,
        run=5,
    ),
    dict(
        label="等01　東京都市大学前",
        type="bus_2",
        file=bus_timetable_file2,
        directions=[
            dict(column="等々力循環", sheet_direction="等々力"),
        ],
        max=2,
        walk=7,
        run=5,
    ),
    # --- ここから追加 ---
    dict(
        label="東急バス　長徳寺前",
        type="bus_csv",
        directions=[
            dict(column="鷺沼駅方面", dest_tag="Saginuma"),
            dict(column="センター北駅方面", dest_tag="CenterKita"),
        ],
        max=3,
        walk=10,
        run=7,
    ),
    # --- ここまで追加 ---
]

# ──────────────────────────────────────────
#  API: 発車案内
# ──────────────────────────────────────────
@app.route("/api/schedule")
def api_schedule():
    labs = ["先発", "次発", "次々発"]
    res = {"current_time": datetime.now().strftime("%H:%M:%S"), "routes": []}

    for r in ROUTES:
        # travel = "(所要時間:15分)" if r["type"] == "train" else "(所要時間:10分)" # この行は削除またはコメントアウト
        # label = f"{r['label']} {travel}" # この行は削除またはコメントアウト
        # label は ROUTES で定義されたものをそのまま使うか、所要時間を動的に表示するなら別途考慮
        ent = {"label": r['label']} # travel情報を削除
        mp = {}

        for d in r.get("directions", []):
            if r["type"] == "train":
                # ─── 電車 (CSV)
                lst = fetch_train_schedule(r["line_code"], d["dest_tag"])
            elif r["type"] == "bus_csv":
                # ─── バス (CSVバージョン) - 追加
                lst = fetch_bus_schedule_csv(r["type"], d["dest_tag"])
            else:
                # ─── バス (Excel)
                sh  = sheet_name(r["type"], d.get("sheet_direction"))
                lst = fetch_bus_schedule(sh, d["column"], r["file"]) # fetch_bus_scheduleも辞書を返すように変更が必要な場合あり

            show, cnt = [], 0
            for item in lst: # item は辞書 {"time": "HH:MM", "type": "種別", "dest": "行き先"} または時刻文字列
                if cnt >= r["max"]:
                    break
                
                current_time_str = ""
                if isinstance(item, dict):
                    current_time_str = item["time"]
                elif isinstance(item, str): # バス時刻表が文字列リストを返す場合
                    current_time_str = item
                else:
                    continue # 不明な形式はスキップ

                rm = remaining(current_time_str)
                if not (0 < rm.total_seconds() < 3600):
                    continue
                mins = rm.seconds // 60
                if mins < r["run"]:
                    continue
                adv = "歩けば間に合います" if mins >= r["walk"] else "走れば間に合います"

                display_parts = [f"{current_time_str}発"]

                if isinstance(item, dict):
                    train_type = item.get("type", "").strip()
                    destination = item.get("dest", "").strip()

                    if train_type and train_type not in ["-", "ー"]:
                        display_parts.append(f"【{train_type}】")
                    if destination and destination not in ["-", "ー"]:
                        display_parts.append(f"{destination}行")
                
                display_parts.append(f"- {mins}分 {adv}")
                show.append(f"{labs[cnt]}: {' '.join(display_parts)}")
                cnt += 1
            mp[d["column"]] = show
        ent["schedules"] = mp
        res["routes"].append(ent)

    return jsonify(res)

# ──────────────────────────────────────────
#  API: 天気情報
# ──────────────────────────────────────────
W_URL = "https://weather.tsukumijima.net/api/forecast/city/130010"


def get_weather() -> dict:
    try:
        return requests.get(W_URL, timeout=6).json()
    except Exception as e:
        print("Weather error:", e)
        return {}


@app.route("/api/weather")
def api_weather():
    return jsonify(get_weather())

# ──────────────────────────────────────────
#  API: ニュース
# ──────────────────────────────────────────
NHK = "https://www3.nhk.or.jp/rss/news/cat0.xml"
GGL = "https://news.google.com/rss/search?q=東急&hl=ja&gl=JP&ceid=JP:ja"


def get_news() -> list[str]:
    out, seen = [], set()
    for url in (NHK, GGL):
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                t = html.unescape(e.title)
                if t not in seen:
                    out.append(t)
                    seen.add(t)
                if len(out) >= 10:
                    break
        except Exception:
            pass
    return out


@app.route("/api/news")
def api_news():
    return jsonify({"news": get_news()})

# ──────────────────────────────────────────
#  API: 運行情報 (Tokyu + ODPT)
#  ※ ここは元スクリプトと同一  … 途中省略 …
# ──────────────────────────────────────────
TOKYU_URL = "https://www.tokyu.co.jp/unten2/unten.html"
CK = "krlf019vch8i8s1qghthm0bingkmxufic5uz2egbhd55mt86gxg3afxvio1z5zbg"
OPS = {
    "東京メトロ": "odpt.Operator:TokyoMetro",
    "都営地下鉄": "odpt.Operator:Toei",
    "多摩モノレール": "odpt.Operator:TamaMonorail",
    "りんかい線": "odpt.Operator:TWR",
    "TX": "odpt.Operator:MIR",
    "横浜市交通局": "odpt.Operator:YokohamaMunicipal",
}

RAIL_NAME_MAP = {
    "Fukutoshin": "副都心線",
    "Namboku": "南北線",
    "Hanzomon": "半蔵門線",
    "Yurakucho": "有楽町線",
    "Chiyoda": "千代田線",
    "Tozai": "東西線",
    "Hibiya": "日比谷線",
    "Marunouchi": "丸の内線",
    "MarunouchiBranch": "丸の内線方南町支線",
    "Ginza": "銀座線",
    "Asakusa": "浅草線",
    "Mita": "三田線",
    "Shinjuku": "新宿線",
    "Oedo": "大江戸線",
    "Arakawa": "都電荒川線（東京さくらトラム）",
    "NipporiToneri": "日暮里舎人ライナー",
    "TamaMonorail": "多摩モノレール",
    "Rinkai": "りんかい線",
    "TsukubaExpress": "つくばエクスプレス線",
    "Green": "横浜市営地下鉄・グリーンライン",
    "Blue": "横浜市営地下鉄・ブルーライン",
}


@lru_cache(maxsize=None)
def get_line_logos(operator_code: str) -> dict[str, str]:
    """事業者ごとの路線ロゴ（systemMap URL）を dict で返す"""
    url = (
        f"https://api.odpt.org/api/v4/odpt:Railway"
        f"?odpt:operator={operator_code}&acl:consumerKey={CK}"
    )
    try:
        js = requests.get(url, timeout=6).json()
        result: dict[str, str] = {}
        for it in js:
            rc = it.get("odpt:railway", "").split(":")[-1].split(".")[-1]
            logo = it.get("odpt:systemMap")
            if logo:
                result[rc] = logo
        return result
    except Exception as e:
        print(f"Railway API error ({operator_code}):", e)
        return {}


def fetch_tokyu() -> list[str]:
    """東急公式サイトをスクレイプし、異常メッセージのみを返す"""
    try:
        r = requests.get(TOKYU_URL, timeout=6)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        msgs: list[str] = []
        for li in soup.select(".service-info li"):
            txt = li.get_text(strip=True)
            if any(w in txt for w in ("平常運転", "通常運転")):
                continue
            tm = li.find("time")
            pre = tm.text.strip() if tm else ""
            msgs.append(f"東急電鉄・{pre}{txt}")
        return msgs
    except Exception as e:
        print("Tokyu scrape error:", e)
        return []


def fetch_odpt() -> list[dict[str, str]]:
    """
    ODPT API から異常情報のみ取得し、
    {"logo": URL or None, "text": "..."} のリストを返す
    """
    base = "https://api.odpt.org/api/v4/odpt:TrainInformation"
    out: list[dict[str, str]] = []

    for op_name, code in OPS.items():
        logos = get_line_logos(code)
        url = f"{base}?odpt:operator={code}&acl:consumerKey={CK}"
        try:
            js = requests.get(url, timeout=6).json()
            for it in js:
                txt = (
                    it.get("odpt:trainInformationText")
                    or it.get("odpt:trainInformationStatus")
                )
                if not txt:
                    continue
                if isinstance(txt, dict):
                    txt = txt.get("ja") or next(iter(txt.values()), "")
                if any(w in txt for w in ("平常運転", "Normal")):
                    continue

                rc = it.get("odpt:railway", "").split(":")[-1].split(".")[-1]
                rail_ja = RAIL_NAME_MAP.get(rc, rc)
                logo = logos.get(rc)
                out.append({"logo": logo, "text": f"{op_name}・{rail_ja}➡{txt}"})
        except Exception as e:
            print(f"ODPT fetch error ({op_name}):", e)

    return out


@app.route("/api/status")
def api_status():
    msgs = fetch_tokyu()
    items: list[dict[str, str]] = [{"logo": None, "text": m} for m in msgs]
    items.extend(fetch_odpt())
    if not items:
        items = [{"logo": None, "text": "各社平常運転です"}]
    return jsonify({"status": items})

# ──────────────────────────────────────────
#  ルート
# ──────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", page=1)


@app.route("/page/<int:p>")
def index_page(p: int):
    return render_template("index.html", page=p)


# ──────────────────────────────────────────
def ensure_csv_encoding():
    """CSVファイルのエンコーディングを確認・修正"""
    # ブルーラインCSV
    bl_files = [
        f"timetable_BL_{day}_{dest}.csv" 
        for day in ["weekday", "holiday"] 
        for dest in ["Azamino", "Shonandai"]
    ]
    
    # 東急バスCSV
    bus_files = [
        f"timetable_BUS_{day}_{dest}.csv"
        for day in ["weekday", "holiday", "saturday"]
        for dest in ["Saginuma", "CenterKita"]
    ]
    
    # 全てのCSVをチェック
    for file_list, file_type in [(bl_files, "ブルーライン"), (bus_files, "東急バス")]:
        for filename in file_list:
            csv_path = DATA_DIR / filename
            if not csv_path.exists():
                print(f"[WARNING] {file_type}時刻表ファイルが見つかりません: {filename}")
                continue
                
            try:
                # ファイルをcp932で読み込んでエンコーディングを確認
                with open(csv_path, 'r', encoding='cp932') as f:
                    content = f.read()
                print(f"[INFO] {file_type}時刻表確認: {filename} (OK)")
            except Exception as e:
                print(f"[ERROR] {file_type}時刻表エンコーディングチェック失敗: {filename} - {e}")

# アプリケーション起動前に実行
if __name__ == "__main__":
    # 既存のコードをrename
    ensure_csv_encoding()
    app.run(debug=True, host="0.0.0.0", port=5000)
