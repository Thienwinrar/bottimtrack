"""
=============================================================
  Bot Tìm Nhạc - Group Ngốc - Sưu Tầm Nhạc
  Lắng nghe topic "Chat - Mò Track Nhạc"
  Tìm trong 13 nhóm nguồn → gửi vào topic + tag người nhắn
  Tự động cập nhật bài mới mỗi 2 tiếng
  Chỉ trả về file có thời lượng từ 3p50s đến dưới 7p
=============================================================

CÁCH DÙNG:
  python bottimtrack.py

LỆNH NGƯỜI DÙNG NHẮN:
  track zinxu         → tìm file có chữ zinxu
  bài chua tung quen  → tìm file tên khớp với chua tung quen

CACHE:
  Xóa file cache_*.json để quét lại toàn bộ nhóm đó
=============================================================
"""

import asyncio
import sys
import io
import json
import re
import unicodedata
import logging
from pathlib import Path
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeAudio

# ─────────────────────────────────────────────
#  FIX ENCODING WINDOWS TERMINAL
# ─────────────────────────────────────────────
safe_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ─────────────────────────────────────────────
#  CẤU HÌNH
# ─────────────────────────────────────────────
API_ID    = 35213698
API_HASH  = "f8168ae92e8a066b132a531e75512ddf"
PHONE     = "+84325298096"

DEST_GROUP    = "t.me/chubengoc_88"
DEST_TOPIC_ID = 14416   # Chat - Mò Track Nhạc

SOURCE_GROUPS = [
    "t.me/Anhemnhaclot",
    "t.me/CongDongAmNhac",
    "t.me/songbacamnhac",
    "t.me/KenhNhacChuaLanh",
    "t.me/tonghoptrack",
    "t.me/nhaclotchatluongcao",
    "t.me/houselaktrack",
    "t.me/NhomTrackNhacLot",
    "t.me/nhomtrackhouselak",
    "t.me/tracknhac",
    "t.me/caubesuutamnhac",
    "t.me/houselaksinhvien",
    "t.me/tracksinhvien",
    "t.me/chubengoc_88",
]

AUDIO_MIME = {
    "audio/mpeg", "audio/mp3", "audio/ogg", "audio/flac",
    "audio/wav", "audio/aac", "audio/m4a", "audio/x-m4a",
    "audio/opus", "audio/mp4", "audio/webm",
}

DEMO_MIN_DURATION  = 240    # 4 phút
UPDATE_INTERVAL    = 2592000  # Cập nhật bài mới mỗi 720 tiếng (giây)

# Chỉ trả kết quả tìm kiếm có thời lượng trong khoảng này
MIN_SEARCH_DURATION = 230   # 3 phút 50 giây
MAX_SEARCH_DURATION = 460   # 7 phút (không tính tròn 7p, dùng < )

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
log = logging.getLogger("bot_nhac")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s │ %(message)s", "%H:%M:%S")
_sh = logging.StreamHandler(safe_stdout)
_sh.setFormatter(fmt)
log.addHandler(_sh)
_fh = logging.FileHandler("bot_nhac.log", encoding="utf-8")
_fh.setFormatter(fmt)
log.addHandler(_fh)

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def slug(text: str) -> str:
    return re.sub(r"\s+", "", normalize(text))

def get_filename(msg) -> str | None:
    if not msg.media or not hasattr(msg.media, "document"):
        return None
    for attr in msg.media.document.attributes:
        if hasattr(attr, "file_name") and attr.file_name:
            return attr.file_name
    return None

def get_duration(msg) -> int:
    if not msg.media or not hasattr(msg.media, "document"):
        return 0
    for attr in msg.media.document.attributes:
        if isinstance(attr, DocumentAttributeAudio):
            return attr.duration or 0
    return 0

def is_audio(msg) -> bool:
    if not msg.media or not hasattr(msg.media, "document"):
        return False
    mime = getattr(msg.media.document, "mime_type", "") or ""
    if mime in AUDIO_MIME:
        return True
    for attr in msg.media.document.attributes:
        if type(attr).__name__ in ("DocumentAttributeAudio", "DocumentAttributeVoice"):
            return True
    return False

def should_skip_demo(fname: str, duration: int) -> bool:
    if "demo" not in fname.lower():
        return False
    return duration < DEMO_MIN_DURATION

def group_slug(link: str) -> str:
    return link.rstrip("/").split("/")[-1].lower()

def cache_path(slug_name: str) -> str:
    return f"cache_{slug_name}.json"

def load_cache(slug_name: str) -> dict:
    """Trả về {"records": [...], "last_id": int}"""
    f = cache_path(slug_name)
    if Path(f).exists():
        try:
            return json.load(open(f, encoding="utf-8"))
        except Exception:
            pass
    return {"records": [], "last_id": 0}

def save_cache(slug_name: str, records: list, last_id: int):
    data = {"records": records, "last_id": last_id}
    json.dump(data, open(cache_path(slug_name), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────
#  PHÂN TÍCH LỆNH
# ─────────────────────────────────────────────

def parse_command(text: str) -> tuple[str, str] | None:
    text = text.strip()
    lower = text.lower()

    m = re.match(r"^track\s+(.+)$", lower)
    if m:
        return ("track", m.group(1).strip())

    m = re.match(r"^b[àa]i\s+(.+)$", lower, re.IGNORECASE)
    if m:
        return ("bai", m.group(1).strip())

    return None

# ─────────────────────────────────────────────
#  QUÉT NHÓM NGUỒN
# ─────────────────────────────────────────────

async def get_records(client, group_link: str) -> list:
    """
    Lần đầu: quét toàn bộ, lưu cache + last_id
    Lần sau: chỉ quét từ last_id trở đi, thêm vào cache
    """
    slug_name = group_slug(group_link)
    cached    = load_cache(slug_name)
    records   = cached["records"]
    last_id   = cached["last_id"]

    if records:
        log.info(f"  [{slug_name}] Cache: {len(records)} file | last_id: {last_id}")
    else:
        log.info(f"  [{slug_name}] Chua co cache, dang quet toan bo...")

    new_records = []
    new_last_id = last_id

    try:
        group = await client.get_entity(group_link)
        async for msg in client.iter_messages(group, limit=None, min_id=last_id):
            if not is_audio(msg):
                continue
            fname = get_filename(msg)
            if not fname:
                continue
            duration = get_duration(msg)
            new_records.append({
                "id":       msg.id,
                "fname":    fname,
                "norm":     normalize(Path(fname).stem),
                "slug":     slug(Path(fname).stem),
                "duration": duration,
                "group":    group_link,
            })
            if msg.id > new_last_id:
                new_last_id = msg.id

        if new_records:
            log.info(f"  [{slug_name}] +{len(new_records)} bai moi")
            records = records + new_records
            save_cache(slug_name, records, new_last_id)
        elif not cached["records"]:
            # Lần đầu quét nhưng không có file nào
            save_cache(slug_name, [], new_last_id)
            log.info(f"  [{slug_name}] Khong co file am thanh")
        else:
            log.info(f"  [{slug_name}] Khong co bai moi")

    except Exception as e:
        log.warning(f"  [{slug_name}] Loi: {e}")

    return records

# ─────────────────────────────────────────────
#  TÌM KIẾM
# ─────────────────────────────────────────────

def search_records(records: list, mode: str, keyword: str) -> list:
    kw_slug = slug(keyword)
    matches = []

    for r in records:
        fname    = r["fname"]
        duration = r["duration"]

        if should_skip_demo(fname, duration):
            continue

        # Chỉ lấy file có thời lượng từ 3p50s đến dưới 7p
        if duration < MIN_SEARCH_DURATION or duration >= MAX_SEARCH_DURATION:
            continue

        slug_stem = r["slug"]

        if mode == "track":
            if kw_slug not in slug_stem:
                continue
        else:
            if kw_slug not in slug_stem:
                continue
            if len(kw_slug) < len(slug_stem) * 0.4:
                continue

        matches.append(r)

    # Loại trùng: giữ file tên ngắn nhất
    seen: dict[str, dict] = {}
    for r in matches:
        key = r["slug"]
        if key not in seen:
            seen[key] = r
        else:
            if len(r["fname"]) < len(seen[key]["fname"]):
                seen[key] = r

    return list(seen.values())

# ─────────────────────────────────────────────
#  GỬI KẾT QUẢ
# ─────────────────────────────────────────────

async def send_results(client, dest_group, results: list, sender_mention: str, keyword: str):
    if not results:
        await client.send_message(
            dest_group,
            f"{sender_mention} ❌ Đéo thấy file {keyword} khổ quá.",
            reply_to=DEST_TOPIC_ID,
        )
        return

    await client.send_message(
        dest_group,
        f"{sender_mention} Mày không có tay à. Đợi tao tý😡\nĐang xem SÉT {keyword}",
        reply_to=DEST_TOPIC_ID,
    )

    for r in results:
        try:
            source_group = await client.get_entity(r["group"])
            msg = await client.get_messages(source_group, ids=r["id"])
            if msg is None:
                continue
            await client.send_file(
                dest_group,
                file=msg.media,
                caption="",
                reply_to=DEST_TOPIC_ID,
            )
            log.info(f"Da gui: {r['fname']}")
            await asyncio.sleep(2)
        except Exception as e:
            log.error(f"Loi gui {r['fname']}: {e}")

# ─────────────────────────────────────────────
#  TỰ ĐỘNG CẬP NHẬT BÀI MỚI
# ─────────────────────────────────────────────

async def auto_update(client, all_records: list):
    """Chạy ngầm, mỗi 2 tiếng quét bài mới từ last_id trở đi."""
    while True:
        await asyncio.sleep(UPDATE_INTERVAL)
        log.info("--- Tu dong cap nhat bai moi (quet tu last_id) ---")
        new_total = 0
        for group_link in SOURCE_GROUPS:
            records = await get_records(client, group_link)
            # Cập nhật all_records tại chỗ
            slug_name = group_slug(group_link)
            # Xóa record cũ của nhóm này, thêm record mới
            all_records[:] = [r for r in all_records if r["group"] != group_link] + records
            new_total += len(records)
        log.info(f"Cap nhat xong: tong {len(all_records)} file tu 13 nhom.\n")

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

async def main():
    client = TelegramClient("My_session", API_ID, API_HASH)
    log.info("Ket noi Telegram...")
    await client.start(phone=PHONE)

    me = await client.get_me()
    log.info(f"Bot dang chay: {me.first_name} (@{me.username})")

    dest_group = await client.get_entity(DEST_GROUP)
    log.info(f"Lang nghe topic {DEST_TOPIC_ID} trong {DEST_GROUP}")

    # Quét/load cache lúc khởi động
    log.info("Dang tai cache 13 nhom nguon...")
    all_records: list = []
    for group_link in SOURCE_GROUPS:
        records = await get_records(client, group_link)
        all_records.extend(records)
    log.info(f"Tong: {len(all_records)} file tu 13 nhom. San sang nhan lenh!\n")

    # Chạy tự động cập nhật bài mới ngầm
    asyncio.create_task(auto_update(client, all_records))

    @client.on(events.NewMessage(chats=dest_group))
    async def handler(event):
        msg = event.message

        # Chỉ xử lý tin nhắn trong đúng topic
        if msg.reply_to and msg.reply_to.reply_to_top_id:
            topic_id = msg.reply_to.reply_to_top_id
        elif msg.reply_to:
            topic_id = msg.reply_to.reply_to_msg_id
        else:
            topic_id = None

        if topic_id != DEST_TOPIC_ID:
            return

        text = msg.text or ""
        parsed = parse_command(text)
        if not parsed:
            return

        mode, keyword = parsed

        sender = await event.get_sender()
        if sender.username:
            mention = f"@{sender.username}"
        else:
            mention = f"[{sender.first_name}](tg://user?id={sender.id})"

        log.info(f"Lenh: [{mode}] '{keyword}' tu {mention}")

        results = search_records(all_records, mode, keyword)
        log.info(f"Tim thay: {len(results)} file")

        await send_results(client, dest_group, results, mention, keyword)

    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot đã dừng!.")