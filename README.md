# Three Out of Forty

Sponsor Challenge — Arctis AI, SiviHack 2026

## 1. Sản phẩm là gì?

Một công ty xây dựng nhận khoảng **40 gói thầu công khai mới mỗi tuần** (thứ Hai), nhưng chỉ đủ năng lực đội ngũ ước tính để bid **3 gói**. Việc chọn sai — bid vào gói không đủ điều kiện, hoặc bỏ lỡ gói phù hợp — tốn hàng tuần công sức ước tính vô ích.

**Three Out of Forty** là công cụ giúp estimator chọn ra 3 gói thầu đáng bid nhất trong tuần, kèm lý do cụ thể (trích dẫn đúng điều khoản gây loại/giữ), thay vì chỉ xếp hạng theo độ "giống" hồ sơ công ty — vì một gói thầu giống ngành/vùng vẫn có thể là **NO cứng** nếu vượt quy mô hợp đồng, vượt hạn mức bảo lãnh, hoặc thiếu reference bắt buộc.

### Đã hoàn thành
- Pipeline thu thập tender xây dựng (CPV bắt đầu bằng `45`) tại Đức từ 2 nguồn công khai: **TED** (ted.europa.eu) và **oeffentlichevergabe.de**.
- Khử trùng lặp giữa 2 nguồn (cùng 1 tender công bố cả 2 nơi khi vượt ngưỡng giá trị EU).
- Trích xuất field quyết định fit/no-fit từ văn bản gốc (Referenzen, Bauzeit, Vertragsstrafe, Bürgschaft, Eigenleistung, Lose).
- Chuẩn hóa 2 nguồn về 1 schema chung (`contract_schema.json`), lưu vào PostgreSQL.

### Đang làm / chưa xong
> _(điền chi tiết task đang dở của từng người ở đây)_

## 2. Hướng dẫn setup và chạy demo

> **TODO — cần thảo luận nhóm trước khi điền:** cách demo cuối cùng sẽ là gì (Swagger API thuần, UI riêng, notebook, hay khác) chưa chốt. Phần dưới đây là các bước đã xác nhận chạy được tới hết bước dữ liệu; bổ sung bước "chạy demo" sau khi nhóm thống nhất.

### Yêu cầu
- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- Docker + Docker Compose (nếu chạy Postgres local) **hoặc** 1 project Postgres trên [Neon](https://neon.tech) (free tier, không cần thẻ)
- Node/[bun](https://bun.sh) — chỉ cần nếu chạy frontend

### Bước 1 — Cấu hình môi trường
Tạo file `.env` ở **gốc repo** (ngang hàng `backend/`, `frontend/`):
```dotenv
SECRET_KEY=<random string>
PROJECT_NAME=Three Out of Forty
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app   # hoặc connection string Neon
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=<mật khẩu>
```

### Bước 2 — Database
**Option A — Docker local:**
```bash
docker compose up -d db
```
**Option B — Neon (cloud, dễ chia sẻ giữa nhiều máy hơn):** tạo project tại neon.tech, dán connection string vào `DATABASE_URL`.

### Bước 3 — Cài dependency & migrate
```bash
cd backend
uv sync
uv run alembic upgrade head
```

### Bước 4 — Chạy pipeline lấy dữ liệu tender
```bash
uv run python app/run_contract_pipelines.py --import-db
```
Chi tiết đầy đủ (flag, biến môi trường, troubleshooting): xem [`CrawlData_InjectionToDatabase_RUNBOOK.md`](./CrawlData_InjectionToDatabase_RUNBOOK.md).

### Bước 5 — Kiểm tra dữ liệu đã vào DB
```bash
uv run python scripts/check_db.py
```

### Bước 6 — Chạy demo
> _TODO — điền sau._

## 3. Công nghệ sử dụng

**Backend**
- [FastAPI](https://fastapi.tiangolo.com) — API framework
- [SQLModel](https://sqlmodel.tiangolo.com) + [Alembic](https://alembic.sqlalchemy.org) — ORM & migration
- [PostgreSQL](https://www.postgresql.org) — database (chạy qua Docker local hoặc [Neon](https://neon.tech))
- [Pydantic](https://docs.pydantic.dev) / pydantic-settings — validate config & data
- [pypdf](https://pypdf.readthedocs.io) — đọc text từ PDF tender

**Hạ tầng / công cụ**
- [uv](https://docs.astral.sh/uv/) — quản lý dependency & virtualenv Python
- [Docker Compose](https://www.docker.com) — chạy Postgres + service phụ trợ local

**Frontend** _(dựng sẵn theo template, chưa customize cho sản phẩm này)_
- React + TypeScript + [Vite](https://vitejs.dev), [Tailwind CSS](https://tailwindcss.com)

## 4. Dataset / API / Library / Template đã sử dụng

**Dataset & API (public, free)**
- [oeffentlichevergabe.de](https://oeffentlichevergabe.de) — Datenservice Öffentlicher Einkauf (Beschaffungsamt des BMI). OCDS JSON + CSV export, giấy phép **CC0**.
- [TED (Tenders Electronic Daily)](https://ted.europa.eu) — cổng thông báo thầu toàn EU, free search API.

**Template**
- [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) (tiangolo) — khung backend + frontend gốc.

**Thư viện Python** — xem đầy đủ, đã pin version, tại [`requirements.txt`](./requirements.txt) (export từ `backend/pyproject.toml` + `uv.lock`). Các thư viện lõi trực tiếp dùng cho pipeline: `fastapi`, `sqlmodel`, `alembic`, `psycopg`, `pandas`, `pypdf`, `httpx`.

## 5. Giới hạn hiện tại

- **Chưa có rules engine** so khớp company profile với tender đã trích xuất — dữ liệu đã sẵn sàng ở DB, phần logic pass/fail chưa viết.
- **Chưa có reasoning layer** sinh giải thích tự động cho estimator.
- **Frontend chưa customize** — vẫn là dashboard User/Item mặc định của template, chưa có màn hình chọn company/xem shortlist.
- **Độ phủ trích xuất chưa đầy đủ** — 1 số field (đặc biệt Vertragsstrafe, Eigenleistung) chỉ xuất hiện trong phụ lục "Besondere Vertragsbedingungen", không phải tender nào cũng tải được phụ lục này.
- **Chỉ tiếng Đức** — không dịch nội dung, cần người đọc hiểu tiếng Đức hoặc dùng công cụ dịch riêng.
- **Không có accuracy metric** — theo đúng tinh thần đề bài (Track_2.pdf mục 7: không có leaderboard/submission file), kết quả được đánh giá qua lý do đưa ra, không qua điểm số.
