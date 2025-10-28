import tkinter as tk
from tkinter import filedialog, messagebox
import yt_dlp
import os
import json
from tkinterdnd2 import DND_FILES, TkinterDnD
import ttkbootstrap as tb

# ✅ ダークテーマとDnDを両立させたウィンドウクラス
class DarkDnDWindow(tb.Window, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        tb.Window.__init__(self, *args, **kwargs)
        self.tk.call('package', 'require', 'tkdnd')


# ===== 設定ファイルの場所 =====
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')

# ===== デフォルト設定 =====
default_config = {
    "save_folder": os.path.dirname(os.path.abspath(__file__)),
    "audio_quality": "192",  # 128 / 192 / 320
    "video_quality": "720"   # 720 / 1080 / 2160
}

# ===== 設定の読み込み・保存 =====AAAA
def load_config():
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_config.copy()

def save_config():
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def fetch_title(url: str) -> str | None:
    """DLしないでメタデータだけ取得してタイトルを返す"""
    if not url:
        return None
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title")
    except Exception:
        return None
    
def update_title(*_):
    url = url_entry.get().strip()
    if not url:
        title_var.set("タイトル: ---")
        return
    title = fetch_title(url)
    if title:
        title_var.set(f"タイトル: {title}")
    else:
        title_var.set("タイトル: (取得失敗)")

def progress_hook(d):
    print(f"[HOOK] status: {d['status']}")
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '').strip()
        print(f"[HOOK] percent: {percent}")
        progress_var.set(f"進捗: {percent}")
        root.update_idletasks()
    elif d['status'] == 'finished':
        print("[HOOK] finished!")
        progress_var.set("進捗: 完了！")


# ===== ダウンロード処理 =====
def download_video(urls, mode):
    output_template = os.path.join(config["save_folder"], '%(title)s.%(ext)s')

    if mode == 'mp3':
        options = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': config["audio_quality"],
            }],
            'progress_hooks': [progress_hook],
            'no_warnings': True,
        }
    elif mode == 'mp4':
        options = {
            'format': f'bestvideo[ext=mp4][height>={config["video_quality"]}]+bestaudio[ext=m4a]/best[ext=mp4][height>={config["video_quality"]}]',
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'progress_hooks': [progress_hook],
            'no_warnings': True,
        }
    else:
        return

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download(urls)
        messagebox.showinfo("完了", f"{mode.upper()} のダウンロードが完了しました")
    except Exception as e:
        messagebox.showerror("エラー", f"ダウンロード中にエラーが発生しました：\n{e}")

# ===== ダウンロードボタン処理 =====
def download_single(mode):
    update_title()
    url = url_entry.get().strip()
    if url:
        download_video([url], mode)

def handle_drop(event):
    path = event.data.strip().strip('{}')  # {} に囲まれてることがあるので除去
    if not path.lower().endswith('.txt'):
        progress_var.set("⚠ 対応しているのは .txt ファイルだけだよ")
        return

    try:
        with open(path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        if urls:
            progress_var.set("進捗: ドロップされたtxtからDL開始")
            download_video(urls, mode='mp4')
        else:
            progress_var.set("⚠ ファイル内に有効なURLが見つからなかったよ")
    except Exception as e:
        progress_var.set(f"⚠ エラー: {e}")


def download_from_txt():
    filepath = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
    if not filepath:
        return
    with open(filepath, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    if urls:
        download_video(urls, mode='mp4')

# ===== 設定画面 =====
def open_settings():
    def browse_folder():
        folder = filedialog.askdirectory()
        if folder:
            folder_var.set(folder)

    def apply_settings():
        config["save_folder"] = folder_var.get()
        config["audio_quality"] = audio_var.get()
        config["video_quality"] = video_var.get()
        save_config()
        settings_window.destroy()
        # messagebox.showinfo("保存完了", "設定を保存しました") ← 必要なら有効にしてね

    settings_window = tb.Toplevel(root)
    settings_window.title("設定")
    settings_window.geometry("400x270")
    settings_window.resizable(False, False)

    # ------- 上部（入力系） -------
    content_frame = tb.Frame(settings_window)
    content_frame.pack(pady=10, fill="x")

    tb.Label(content_frame, text="保存先フォルダ:").pack(pady=5)
    folder_var = tb.StringVar(value=config["save_folder"])
    folder_entry = tb.Entry(content_frame, textvariable=folder_var, width=50)
    folder_entry.pack()
    tb.Button(content_frame, text="参照...", command=browse_folder).pack(pady=5)

    tb.Label(content_frame, text="MP3音質（kbps）:").pack(pady=5)
    audio_var = tb.StringVar(value=config["audio_quality"])
    tb.OptionMenu(content_frame, audio_var, audio_var.get(), "128", "192", "320").pack()

    tb.Label(content_frame, text="MP4画質:").pack(pady=5)
    video_var = tb.StringVar(value=config["video_quality"])
    tb.OptionMenu(content_frame, video_var, video_var.get(), "720", "1080", "2160").pack()

    # ------- 下部（ボタン） -------
    button_frame = tb.Frame(settings_window)
    button_frame.pack(side="bottom", pady=10)
    tk.Button(
        button_frame, 
        text="保存して閉じる", 
        width=25,
        height=10,
        command=apply_settings
        ).pack()
    
    settings_window.update()
    settings_window.minsize(settings_window.winfo_width(), settings_window.winfo_height())

# ===== GUI画面構築 =====
config = load_config()

root = TkinterDnD.Tk()
style = tb.Style(theme="darkly")  # 後からダーク配色を流し込む
style.master=root
style.configure('.', foreground='white')  
root.title("YouTube ダウンローダー")

title_var = tb.StringVar(value="タイトル: ---")
title_label = tb.Label(root, textvariable=title_var)
title_label.pack(pady=(10, 0))

tb.Label(root, text="YouTubeのURLを入力してね").pack(pady=5)
url_entry = tb.Entry(root, width=65)
url_entry.pack(pady=5)

url_entry.drop_target_register(DND_FILES)
url_entry.dnd_bind('<<Drop>>', handle_drop)

# Enter キーでタイトルを更新
url_entry.bind("<Return>", update_title)
url_entry.bind("<FocusOut>", update_title)

tb.Button(root, text="MP3で保存", command=lambda: download_single('mp3')).pack(pady=5)
tb.Button(root, text="MP4で保存", command=lambda: download_single('mp4')).pack(pady=5)
tb.Button(root, text="txtからMP4一括保存", command=download_from_txt).pack(pady=5)
tb.Button(root, text="⚙ 設定", command=open_settings).pack(pady=15)

progress_var = tb.StringVar(value="進捗: ---")
progress_label = tb.Label(root, textvariable=progress_var)
progress_label.pack(pady=5)

root.update()
root.minsize(root.winfo_width(), root.winfo_height())

root.mainloop()
