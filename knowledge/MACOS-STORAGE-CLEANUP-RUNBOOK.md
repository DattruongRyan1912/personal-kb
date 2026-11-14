---
id: PKB-STORAGE-RUNBOOK
title: "Runbook: Hướng dẫn Dọn dẹp Dung lượng macOS An Toàn"
project: Personal-KB
owner: "Ryan Truong"
status: active
last_updated: "2026-10-31"
tags: [runbook, macos, storage, cleanup, docker, volumes, ollama, avd, safety]
---

# Runbook: Hướng Dẫn Dọn Dẹp Dung Lượng Ổ Đĩa macOS An Toàn

Tài liệu này cung cấp quy chuẩn và checklist bắt buộc cho Developer và AI Agent khi thực hiện khảo sát, dọn dẹp và thu hồi dung lượng ổ cứng (disk space) trên môi trường phát triển macOS, bảo đảm **tuyệt đối không làm mất dữ liệu database** và **không làm gián đoạn hạ tầng search/AI đang hoạt động**.

---

## 1. Nguyên Tắc Bất Khả Xâm Phạm (Negative Constraints)

> [!CAUTION]
> **[FORBIDDEN] [NC-PKB-STORAGE-001] CẤM TUYỆT ĐỐI XOÁ HOẶC PRUNE DOCKER VOLUMES**
> - **CẤM** chạy lệnh `docker system prune --volumes` hoặc `docker system prune -a --volumes`.
> - **CẤM** chạy lệnh `docker volume prune` hoặc xoá thủ công các volume cơ sở dữ liệu khi chưa có xác nhận và backup.
> - **Lý do & Dẫn chứng:** Toàn bộ dữ liệu PostgreSQL (`personal-kb_postgres_data` chứa worklog, Demo-Core identity/payroll) và các volume Supabase local (`supabase_*`) được lưu trữ bền vững trên Docker Volumes. Bảng `worklog` là dữ liệu duy nhất **không thể tự động dựng lại từ `knowledge/`** ([PKB-01]). Xoá volume sẽ làm mất vĩnh viễn toàn bộ cơ sở dữ liệu dự án.
> - Luôn chạy lệnh đối soát danh sách volume trước khi dọn:
>   ```bash
>   docker volume ls
>   ```

> [!CAUTION]
> **[FORBIDDEN] [NC-PKB-STORAGE-002] CẤM XOÁ MODEL RERANKER TRONG HUGGINGFACE HUB CACHE**
> - **CẤM** chạy lệnh wildcard `rm -rf ~/.cache/huggingface/hub/*`.
> - **CẤM XÓA** thư mục `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3`.
> - **Lý do & Dẫn chứng:** Dịch vụ Reranker cục bộ `BAAI/bge-reranker-v2-m3` chạy daemon qua launchd ở cổng `:8081` ([PKB-01], [PKB-05]). Nếu xoá cache này, tiến trình reranker sẽ sập hoặc phải tải lại ~2.2 GB weights, khiến toàn bộ tác vụ MCP `search_knowledge` bị trả về kết quả chưa qua reranking (score thấp, cảnh báo warning).

> [!CAUTION]
> **[FORBIDDEN] [NC-PKB-STORAGE-003] CẤM XOÁ MODEL EMBEDDING TRONG OLLAMA**
> - **CẤM** chạy `ollama rm bge-m3` hoặc xoá model embedding được chỉ định trong file `.env` (`EMBEDDING_MODEL=bge-m3`).
> - **Lý do & Dẫn chứng:** Backend `personal-kb` lấy vector embedding từ Ollama cổng `:11434` với model `bge-m3` ([PKB-01], [PKB-05]). Model này sinh vector 1024 chiều khớp với kiểu dữ liệu `vector(1024)` trong PostgreSQL. Nếu xoá hoặc đổi sang model khác, toàn bộ pipeline ingest tài liệu và vector search sẽ lập tức ngừng hoạt động.

> [!CAUTION]
> **[FORBIDDEN] [NC-PKB-STORAGE-004] CẤM TỰ Ý TẠO NHIỀU MÁY ẢO ANDROID & KHỞI CHẠY >1 EMULATOR (SHARED AVD INVARIANT)**
> - **CẤM** tạo máy ảo Android riêng lẻ theo từng repo dự án (như `Ledgerly_Pixel_8`). Bắt buộc dùng chung 01 máy ảo chuẩn (`MemeVault_API_35_Play` hoặc `Pixel_8_API35`) và cài đặt chung nhiều ứng dụng lên cùng máy ảo đó.
> - **CẤM** khởi động đồng thời nhiều hơn 1 tiến trình `qemu-system-aarch64`. Trước khi khởi động emulator, BẮT BUỘC kiểm tra `adb devices` hoặc `pgrep qemu-system-aarch64`.
> - **Lý do & Dẫn chứng:** Mỗi máy ảo chiếm 6–10 GB ổ cứng và mỗi tiến trình emulator chiếm 6–8.5 GB RAM ngầm. Khởi chạy song song gây cạn kiệt RAM (>16 GB ngốn ngầm qua nhiều ngày như sự cố worklog #187). Sau khi hoàn tất kiểm thử, phải tắt emulator bằng `adb emu kill`.

---

## 2. Quy Trình Dọn Dẹp An Toàn

### Bước 1: Dọn Dẹp Docker Desktop (Chỉ Xoá Image & Build Cache Tạm)
Chỉ thu hồi dung lượng từ build layer và container đã dừng, bảo vệ 100% volumes:
```bash
# 1. Kiểm tra danh sách container hiện có (bao gồm container đã dừng)
docker ps -a

# 2. Xoá container đã dừng (không ảnh hưởng volumes)
docker container prune -f

# 3. Xoá build cache tạm tích tụ lâu ngày (thường giải phóng 10 - 30 GB)
docker builder prune -f

# 4. Xoá các Docker image không còn gắn thẻ (dangling images)
docker image prune -f
```

---

### Bước 2: Dọn Dẹp Mô Hình AI Cục Bộ (LLM - Ollama & HuggingFace)
Mỗi mô hình LLM cục bộ chiếm từ 4 GB đến 40 GB. Cần phân loại rõ mô hình sản xuất và mô hình thử nghiệm:

1. **Mô hình BẮT BUỘC GIỮ LẠI:**
   - `bge-m3` (Ollama): Bắt buộc cho Personal-KB vector embedding, 1024 chiều ([PKB-01]).
   - `models--BAAI--bge-reranker-v2-m3` (HuggingFace Hub): Bắt buộc cho Reranker Service port 8081 ([PKB-05]).
   - `qwen3:8b` (Ollama): Mô hình LLM chính phục vụ coding và agent orchestration.

2. **Dọn dẹp Ollama an toàn:**
   - Luôn đối chiếu `EMBEDDING_MODEL` trong `.env` trước khi xoá bất kỳ model nào:
     ```bash
     ollama list
     # Chỉ xoá model thử nghiệm không sử dụng (ví dụ: gemma4:latest)
     ollama rm gemma4:latest
     ```

3. **Dọn dẹp HuggingFace Hub Cache có chọn lọc (KHÔNG DÙNG WILDCARD):**
   ```bash
   # Quét dung lượng từng model trong cache
   huggingface-cli scan-cache
   
   # Chỉ xoá model thử nghiệm không dùng, TUYỆT ĐỐI KHÔNG xoá models--BAAI--bge-reranker-v2-m3:
   # rm -rf ~/.cache/huggingface/hub/models--<tên_org>--<tên_model_không_dùng>
   ```

---

### Bước 3: Tối Ưu Máy Ảo Android (AVD Emulator) & Chế Tài Tái Sử Dụng
- **Quy tắc công thái học & [NC-PKB-STORAGE-004]:** Tuyệt đối CẤM tạo máy ảo riêng theo từng dự án (MyNotch, Ledgerly, MemeVault, HRM Mobile). Mỗi AVD snapshot chiếm từ 6 GB đến 10 GB ổ cứng và ngốn 8.5 GB RAM ngầm.
- **Giải pháp:** Bắt buộc sử dụng **01 máy ảo chuẩn duy nhất** (`MemeVault_API_35_Play` hoặc `Pixel_8_API35`). Có thể cài đặt song song hàng chục ứng dụng APK lên cùng một máy ảo như một chiếc điện thoại thực tế qua `adb install` hoặc `flutter run`.
- **Quản lý tiến trình:** Trước khi mở emulator, kiểm tra `adb devices`. CẤM mở >1 instance `qemu-system-aarch64`. Sau khi test xong, tắt bằng `adb emu kill`.
- **Xoá máy ảo thừa:**
  ```bash
  # Liệt kê danh sách AVD
  emulator -list-avds
  
  # Xoá AVD thừa không dùng
  avdmanager delete avd -n <ten_avd_thua>
  ```

---

### Bước 4: Dọn Dẹp Build Artifacts & Package Caches Hệ Thống

1. **Xcode DerivedData (Thường chiếm 20 - 50 GB):**
   ```bash
   rm -rf ~/Library/Developer/Xcode/DerivedData/*
   ```
2. **Homebrew Cache:**
   ```bash
   brew cleanup -s
   rm -rf $(brew --cache)
   ```
3. **Gradle & Android Caches:**
   ```bash
   rm -rf ~/.gradle/caches/build-cache-*
   ```
4. **Python & Package Manager Caches:**
   ```bash
   uv cache clean
   pip cache purge
   ```

---

## 3. Checklist Kiểm Tra An Toàn Trước Khi Thực Thi

| Hạng mục | Được phép xoá? | Lệnh an toàn / Hành động | Rủi ro nếu làm sai |
| :--- | :---: | :--- | :--- |
| **Docker Build Cache** | ✅ CÓ | `docker builder prune -f` | Không rủi ro |
| **Docker Dangling Images** | ✅ CÓ | `docker image prune -f` | Không rủi ro |
| **Docker Volumes (`personal-kb_postgres_data`)** | ❌ **CẤM** | **TUYỆT ĐỐI KHÔNG CHẠY PRUNE** | **MẤT TRẮNG DỮ LIỆU DATABASE & WORKLOG** |
| **Model Ollama `bge-m3`** | ❌ **CẤM** | **CẤM XOÁ** (Check `.env`) | **HỎNG VECTOR SEARCH & INGEST** |
| **Model HF `bge-reranker-v2-m3`** | ❌ **CẤM** | **CẤM XOÁ** | **SẬP RERANKER SERVICE PORT 8081** |
| **LLM Model Thử Nghiệm (Ollama)** | ✅ CÓ | `ollama rm <model_thua>` | Tải lại khi cần |
| **Tạo mới AVD khi đã có sẵn** | ❌ **CẤM** | **Dùng chung AVD chuẩn (`MemeVault_API_35_Play`)** | **Lãng phí 6-10GB disk, cạn kiệt 8.5GB RAM ngầm** |
| **AVD Máy ảo trùng lặp / Thừa** | ✅ CÓ | `avdmanager delete avd -n ...` | Xoá app trong máy ảo đó |
| **Xcode DerivedData** | ✅ CÓ | `rm -rf ~/Library/Developer/Xcode/DerivedData/*` | Lần build đầu sẽ compile lại |
