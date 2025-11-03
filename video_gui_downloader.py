import asyncio
import json
import os
import threading
from typing import List, Optional

import flet as ft
import yt_dlp

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
DEFAULT_CONFIG = {
    "save_folder": os.path.dirname(os.path.abspath(__file__)),
    "audio_quality": "192",
    "video_quality": "720",
}
_CONFIG_LOCK = threading.Lock()

COLOR_INFO = "#37474F"
COLOR_SUCCESS = "#2E7D32"
COLOR_WARNING = "#FFB300"
COLOR_ERROR = "#C62828"


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            merged = DEFAULT_CONFIG.copy()
            merged.update(data)
            return merged
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    os.makedirs(cfg.get("save_folder", DEFAULT_CONFIG["save_folder"]), exist_ok=True)
    with _CONFIG_LOCK:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp, indent=2, ensure_ascii=False)


def fetch_title(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("title")
    except Exception:
        return None


def extract_urls_from_txt(path: str) -> List[str]:
    encodings = ("utf-8", "utf-8-sig", "cp932", "shift_jis")
    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding) as fp:
                return [line.strip() for line in fp if line.strip()]
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as fp:
        return [line.strip() for line in fp if line.strip()]


def make_ytdlp_options(mode: str, cfg: dict, progress_hook):
    output_template = os.path.join(cfg["save_folder"], "%(title)s.%(ext)s")
    common = {
        "outtmpl": output_template,
        "progress_hooks": [progress_hook],
        "no_warnings": True,
    }

    if mode == "mp3":
        options = {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": cfg.get("audio_quality", DEFAULT_CONFIG["audio_quality"]),
                }
            ],
        }
    elif mode == "mp4":
        try:
            target_height = int(cfg.get("video_quality", DEFAULT_CONFIG["video_quality"]))
        except (TypeError, ValueError):
            target_height = int(DEFAULT_CONFIG["video_quality"])

        video_candidates = [
            f"bv*[ext=mp4][height<={target_height}]",
            f"bv*[height<={target_height}]",
            "bv*[ext=mp4]",
            "bv*",
        ]
        audio_candidates = [
            "ba[ext=m4a]",
            "ba",
        ]

        format_chain = [f"{v}+{a}" for v in video_candidates for a in audio_candidates]
        format_chain.extend(["b[ext=mp4]", "best"])

        options = {
            **common,
            "format": "/".join(format_chain),
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ],
        }
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return options


config = load_config()


def main(page: ft.Page) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    def handle_asyncio_exception(loop_obj, context):
        exc = context.get("exception")
        if isinstance(exc, RuntimeError) and "after shutdown" in str(exc):
            return
        loop_obj.default_exception_handler(context)

    def safe_run_in_executor(self, executor, func, *args):
        try:
            return self.__original_run_in_executor(executor, func, *args)
        except RuntimeError as exc:
            if "after shutdown" in str(exc):
                try:
                    fut = asyncio.get_event_loop().create_future()
                except RuntimeError:
                    fut = asyncio.Future()
                fut.set_result(None)
                return fut
            raise

    if loop is not None:
        loop.set_exception_handler(handle_asyncio_exception)
        if not hasattr(loop, "__original_run_in_executor"):
            loop.__original_run_in_executor = loop.run_in_executor
            loop.run_in_executor = safe_run_in_executor.__get__(loop, asyncio.AbstractEventLoop)

    page.title = "動画ダウンローダー (Flet)"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    title_text = ft.Text("タイトル: ---", selectable=True)
    progress_text = ft.Text("進捗: ---")
    folder_text = ft.Text(config["save_folder"], size=12, selectable=True)

    url_field = ft.TextField(
        label="動画URL",
        width=500,
        autofocus=True,
        on_submit=lambda _: update_title(),
        on_blur=lambda _: update_title(),
    )

    audio_dropdown = ft.Dropdown(
        label="MP3音質 (kbps)",
        options=[ft.dropdown.Option(value) for value in ["128", "192", "320"]],
        value=config.get("audio_quality", DEFAULT_CONFIG["audio_quality"]),
        width=160,
    )

    video_dropdown = ft.Dropdown(
        label="MP4画質",
        options=[ft.dropdown.Option(value) for value in ["720", "1080", "2160"]],
        value=config.get("video_quality", DEFAULT_CONFIG["video_quality"]),
        width=160,
    )

    download_controls: List[ft.Control] = []
    app_state = {"active": True}

    def mark_inactive(_=None) -> None:
        app_state["active"] = False

    if hasattr(page, "on_disconnect"):
        page.on_disconnect = mark_inactive
    if hasattr(page, "on_close"):
        page.on_close = mark_inactive

    def notify(event_type: str, **payload) -> None:
        if not app_state["active"]:
            return
        try:
            page.pubsub.send_all({"type": event_type, **payload})
        except RuntimeError:
            mark_inactive()

    def setattr_and_update(control: ft.Control, field: str, value):
        if not app_state["active"]:
            return
        setattr(control, field, value)
        try:
            control.update()
        except RuntimeError:
            mark_inactive()

    def update_title() -> None:
        url = (url_field.value or "").strip()
        if not url:
            setattr_and_update(title_text, "value", "タイトル: ---")
            return

        setattr_and_update(title_text, "value", "タイトル: 取得中...")

        def worker():
            title = fetch_title(url)
            message = f"タイトル: {title}" if title else "タイトル: (取得失敗)"
            notify("title", value=message)

        threading.Thread(target=worker, daemon=True).start()

    def handle_event(message: dict) -> None:
        if not app_state["active"]:
            return
        event_type = message.get("type")
        if event_type == "title":
            setattr_and_update(title_text, "value", message.get("value", "タイトル: ---"))
        elif event_type == "progress":
            setattr_and_update(progress_text, "value", message.get("value", "進捗: ---"))
        elif event_type == "snackbar":
            show_snackbar(message.get("message", ""), message.get("color", COLOR_INFO))
        elif event_type == "download_success":
            handle_download_success(message.get("mode", ""))
        elif event_type == "download_error":
            handle_download_error(message.get("message", ""))
        elif event_type == "start_download":
            start_download(message.get("mode"), message.get("urls", []))

    page.pubsub.subscribe(handle_event)

    def show_snackbar(message: str, color: str = COLOR_INFO) -> None:
        if not app_state["active"]:
            return
        if threading.current_thread() is threading.main_thread():
            try:
                page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=color)
                page.snack_bar.open = True
                page.update()
            except RuntimeError:
                mark_inactive()
        else:
            notify("snackbar", message=message, color=color)

    def set_busy(is_busy: bool) -> None:
        if not app_state["active"]:
            return
        for ctrl in download_controls:
            ctrl.disabled = is_busy
            try:
                ctrl.update()
            except RuntimeError:
                mark_inactive()
                return
        url_field.disabled = is_busy
        try:
            url_field.update()
        except RuntimeError:
            mark_inactive()

    def handle_download_success(mode: str):
        set_busy(False)
        setattr_and_update(progress_text, "value", "進捗: 完了")
        show_snackbar(f"{mode.upper()} のダウンロードが完了しました", COLOR_SUCCESS)

    def handle_download_error(message: str):
        set_busy(False)
        setattr_and_update(progress_text, "value", "進捗: エラー")
        show_snackbar(f"ダウンロードに失敗しました: {message}", COLOR_ERROR)

    def start_download(mode: str, urls: List[str]) -> None:
        urls = [u.strip() for u in urls if u and u.strip()]
        if not urls:
            show_snackbar("有効なURLが見つかりません", COLOR_WARNING)
            return

        set_busy(True)
        setattr_and_update(progress_text, "value", "進捗: 開始しています...")

        with _CONFIG_LOCK:
            current_config = config.copy()

        os.makedirs(current_config.get("save_folder", DEFAULT_CONFIG["save_folder"]), exist_ok=True)

        def progress_hook(data: dict) -> None:
            status = data.get("status")
            if status == "downloading":
                percent = (data.get("_percent_str") or "").strip()
                if percent:
                    notify("progress", value=f"進捗: {percent}")
            elif status == "finished":
                notify("progress", value="進捗: 変換中...")

        def worker():
            try:
                options = make_ytdlp_options(mode, current_config, progress_hook)
                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download(urls)
            except Exception as exc:
                notify("download_error", message=str(exc))
                return

            notify("download_success", mode=mode)

        threading.Thread(target=worker, daemon=True).start()

    def handle_directory_pick(e: ft.FilePickerResultEvent) -> None:
        if not e.path:
            return
        config["save_folder"] = e.path
        save_config(config)
        setattr_and_update(folder_text, "value", e.path)
        show_snackbar("保存先フォルダーを更新しました", COLOR_SUCCESS)

    def handle_audio_change(_: ft.ControlEvent) -> None:
        config["audio_quality"] = audio_dropdown.value or DEFAULT_CONFIG["audio_quality"]
        save_config(config)
        show_snackbar("MP3音質を保存しました", COLOR_SUCCESS)

    def handle_video_change(_: ft.ControlEvent) -> None:
        config["video_quality"] = video_dropdown.value or DEFAULT_CONFIG["video_quality"]
        save_config(config)
        show_snackbar("MP4画質を保存しました", COLOR_SUCCESS)

    def read_txt_and_download(path: str, mode: str) -> None:
        setattr_and_update(progress_text, "value", "進捗: リストを読み込み中...")

        def reader():
            try:
                urls = extract_urls_from_txt(path)
            except Exception as exc:
                notify("snackbar", message=f"ファイルを読み込めませんでした: {exc}", color=COLOR_ERROR)
                return

            if not urls:
                notify("snackbar", message="ファイル内に有効なURLがありません", color=COLOR_WARNING)
                return

            notify("start_download", mode=mode, urls=urls)

        threading.Thread(target=reader, daemon=True).start()

    bulk_mode = {"value": "mp4"}

    def handle_txt_pick(e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        file_path = e.files[0].path
        if not file_path:
            show_snackbar("ファイルパスを取得できませんでした", COLOR_WARNING)
            return
        if not file_path.lower().endswith(".txt"):
            show_snackbar("対応しているのは .txt ファイルだけです", COLOR_WARNING)
            return
        read_txt_and_download(file_path, bulk_mode["value"])

    def request_txt_pick(mode: str) -> None:
        bulk_mode["value"] = mode
        file_picker.pick_files(allowed_extensions=["txt"], allow_multiple=False)

    directory_picker = ft.FilePicker(on_result=handle_directory_pick)
    file_picker = ft.FilePicker(on_result=handle_txt_pick)
    page.overlay.extend([directory_picker, file_picker])

    audio_dropdown.on_change = handle_audio_change
    video_dropdown.on_change = handle_video_change

    mp3_button = ft.ElevatedButton(
        "MP3で保存",
        on_click=lambda _: start_download("mp3", [url_field.value or ""]),
    )
    mp4_button = ft.ElevatedButton(
        "MP4で保存",
        on_click=lambda _: start_download("mp4", [url_field.value or ""]),
    )
    mp4_from_txt = ft.ElevatedButton(
        "txtからMP4で一括保存",
        on_click=lambda _: request_txt_pick("mp4"),
    )
    mp3_from_txt = ft.ElevatedButton(
        "txtからMP3で一括保存",
        on_click=lambda _: request_txt_pick("mp3"),
    )
    folder_button = ft.ElevatedButton(
        "保存先を変更",
        on_click=lambda _: directory_picker.get_directory_path(),
    )

    download_controls.extend([mp3_button, mp4_button, mp4_from_txt, mp3_from_txt])

    page.add(
        ft.Column(
            [
                title_text,
                url_field,
                ft.Row(
                    [
                        ft.Column(
                            [mp3_button, mp3_from_txt],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=10,
                        ),
                        ft.Column(
                            [mp4_button, mp4_from_txt],
                            alignment=ft.MainAxisAlignment.CENTER,
                            horizontal_alignment=ft.CrossAxisAlignment.START,
                            spacing=10,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10,
                    tight=True,
                ),
                ft.Divider(),
                ft.Text(".txtファイルを選んで一括ダウンロードを実行できます。"),
                ft.Divider(),
                ft.Row(
                    [audio_dropdown, video_dropdown],
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                ),
                ft.Row(
                    [folder_button, folder_text],
                    alignment=ft.MainAxisAlignment.CENTER,
                    wrap=True,
                ),
                progress_text,
            ],
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
    )

    setattr_and_update(title_text, "value", "タイトル: ---")
    setattr_and_update(progress_text, "value", "進捗: ---")


if __name__ == "__main__":
    ft.app(target=main)
