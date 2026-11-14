---
id: KB-01
title: Hướng dẫn sử dụng Kho Tri Thức Cá Nhân
owner: Ryan Truong
status: APPROVED
---
# 1. Tổng quan
Đây là kho tri thức cá nhân riêng biệt của bạn trên hệ thống CyberOS AI, được lưu trữ độc lập trong cơ sở dữ liệu `personal_memory` trên PostgreSQL 17 + pgvector.

## 1.1 Tính năng chính
- Lưu trữ riêng biệt, không bị trộn lẫn với các tài liệu SPC của dự án chính.
- Hỗ trợ đầy đủ tìm kiếm Vector ngữ nghĩa (BGE-M3) và Đồ thị quan hệ (Graph Facts).
- Phản hồi cực nhanh thông qua API chuyên dụng cổng 8002.

# 2. Cách thêm tài liệu mới
1. Thả bất kỳ file Markdown (`.md`) nào vào thư mục `ai/personal_kb/docs/`.
2. Chạy lệnh: `./ingest.sh` trong thư mục `ai/personal_kb/`.
3. Hệ thống sẽ tự động băm nhỏ, sinh vector và phân tích đồ thị quan hệ vào kho cá nhân.
