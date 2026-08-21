# dataset_web — เว็บเผยแพร่ชุดข้อมูลท่ารำโนรา

หน้าเว็บสองภาษาสำหรับเผยแพร่ชุดข้อมูลโนรา พร้อมระบบขอสิทธิ์ดาวน์โหลด
deploy ด้วย Docker บน `ainora-agent` หลัง nginx ที่มีอยู่เดิม

---

## หลักการออกแบบสองข้อ

**1. โค้ดอยู่ใน Git ข้อมูลอยู่บนดิสก์**

repo นี้เก็บเฉพาะโค้ดเว็บกับไฟล์แคตตาล็อก (`data/*.json`) รวมไม่กี่ร้อย KB
ตัวไฟล์ dataset จริงอยู่บน volume ของเซิร์ฟเวอร์ที่ `/srv/ainora/dataset/<version>/`
Docker image จึงเล็กและ deploy ได้บ่อยโดยไม่ต้องขน GB ผ่าน CI ทุกรอบ
และการอัปเดตข้อมูลก็ไม่ต้อง rebuild image

**2. nginx จองแค่ `/dataset/` ที่เหลือเป็นเรื่องของแอป**

nginx มี location เดียวและ proxy ทุกอย่างเข้ามา เส้นทางข้างในทั้งหมด —
`/api/catalog`, `/api/access`, `/api/download/{id}`, ไฟล์ static —
จัดการในระดับแอปพลิเคชัน เพิ่ม endpoint ใหม่ได้โดยไม่ต้องแตะ nginx อีกเลย
และ nginx ไม่ต้องเห็นไฟล์ dataset จึงไม่ต้องแชร์ volume กับ container

---

## โครงสร้าง

```
dataset_web/
├── app/
│   ├── config.py            อ่านค่าทั้งหมดจาก environment
│   ├── auth.py              โทเคน HMAC (stateless, หมุน SECRET_KEY = เพิกถอนทุกใบ)
│   ├── db.py                SQLite: access_request + download_event
│   ├── main.py              /api/catalog, /api/access, /api/download/{id}
│   └── static/              หน้าเว็บ (ไม่มี build step, ไม่มี framework)
├── data/
│   ├── manifest.json        แคตตาล็อก — ขับเคลื่อนทั้งหน้าเว็บ
│   └── poses.json           ชื่อท่ามาตรฐาน 12 ท่า + aliases + สถานะภาพ
├── scripts/
│   ├── bundles.config.json  whitelist ว่าไฟล์ไหนเข้า bundle ไหน
│   ├── build_bundles.py     แพ็ก zip + sha256 + อัปเดต manifest
│   ├── audit_bundles.py     ตรวจ zip ที่แพ็กแล้วว่าไม่มีไฟล์ต้องห้ามหลุด
│   ├── validate_catalog.py  ตรวจ manifest/poses/i18n ก่อนขึ้น (รันใน CI)
│   └── pdpa_tool.py         export / subject / erase / purge / stats
├── deploy/
│   ├── nginx-host.conf.example   config ที่ต้องเอาไปใส่ nginx บนเครื่อง
│   └── docker-compose.yml
├── tests/test_api.py        17 เทสต์ เน้นพิสูจน์ว่า gate กันได้จริง
├── Dockerfile
├── .github/workflows/ci.yml
└── Jenkinsfile
```

---

## รันในเครื่อง

```bash
pip install -r requirements.txt

export SECRET_KEY=$(openssl rand -hex 32)
export DATA_DIR=/tmp/nora-data
export DB_PATH=/tmp/nora-db/access.sqlite3
export USE_XACCEL=false          # ไม่มี nginx ให้แอปส่งไฟล์เอง

mkdir -p $DATA_DIR/0.1.0-draft
uvicorn app.main:app --reload --port 8099
```

เปิด http://127.0.0.1:8099/

```bash
pytest tests -q
ruff check app scripts tests
python3 scripts/validate_catalog.py
```

---

## แพ็กและเผยแพร่ข้อมูล

```bash
# 1. ดูก่อนว่าจะมีอะไรเข้า bundle บ้าง (ไม่เขียนไฟล์)
python3 scripts/build_bundles.py --dry-run

# 2. แพ็กจริง — เขียนลง dist/<version>/ แล้วอัปเดต data/manifest.json ให้เอง
python3 scripts/build_bundles.py

# 3. ตรวจซ้ำว่าไม่มีไฟล์ต้องห้ามหลุดเข้าไป — ห้ามข้ามขั้นนี้
python3 scripts/audit_bundles.py dist/0.1.0-draft

# 4. ส่งขึ้นเซิร์ฟเวอร์
rsync -av --progress dist/0.1.0-draft/ ainora-agent:/srv/ainora/dataset/0.1.0-draft/

# 5. commit manifest ที่อัปเดตแล้ว → GitHub Actions build → Jenkins deploy
git add data/manifest.json && git commit -m "release 0.1.0" && git push
```

`build_bundles.py` ใช้ **whitelist** เท่านั้น ไฟล์จะเข้า bundle ก็ต่อเมื่อ
`bundles.config.json` ระบุชื่อไว้ตรง ๆ หรือระบุโฟลเดอร์พร้อม pattern ที่ตรงกัน
เพราะโฟลเดอร์ต้นทางมีทั้งเอกสาร TOR ใบเสนอราคา invoice และวิดีโอจาก TikTok ปนอยู่
ถ้าใช้ blacklist สักวันจะพลาด

`audit_bundles.py` ตรวจ zip ที่แพ็กเสร็จแล้วอีกชั้นโดยไม่เชื่อ config
เผื่อวันหนึ่งมีคนแก้ config แล้วเผลอเปิดช่อง

---

## ติดตั้งบนเซิร์ฟเวอร์

```bash
# โครงไดเรกทอรี
mkdir -p /srv/ainora/dataset /srv/ainora/dataset-db /srv/ainora/dataset-web
cp deploy/docker-compose.yml /srv/ainora/dataset-web/

# ความลับสำหรับเซ็นโทเคน — เก็บใน Jenkins credentials ชื่อ nora-dataset-secret-key
openssl rand -hex 32
```

เอา location ใน `deploy/nginx-host.conf.example` ไปใส่ใน server block เดิม
แล้ว `nginx -t && systemctl reload nginx`

nginx จอง path เดียวคือ `/dataset/` แล้ว proxy ทุกอย่างเข้ามาที่บริการนี้
อะไรที่อยู่หลัง `/dataset/` — หน้าเว็บ, API, ฟอร์ม, การดาวน์โหลดไฟล์ —
จัดการในระดับแอปพลิเคชันทั้งหมด nginx ไม่ต้องรู้จักโครงสร้างข้างในเลย

```nginx
location /dataset/ {
    proxy_pass         http://127.0.0.1:10095/;
    proxy_http_version 1.1;

    proxy_set_header Host               $http_host;
    proxy_set_header X-Real-IP          $remote_addr;
    proxy_set_header X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto  $scheme;
    proxy_set_header X-Forwarded-Prefix /dataset;

    proxy_connect_timeout 5s;
    proxy_read_timeout    60s;

    proxy_buffering          off;
    proxy_max_temp_file_size 0;
    proxy_send_timeout       1h;
}
```

ไฟล์ dataset mount เข้า **container เท่านั้น** (`/srv/ainora/dataset:/data:ro`)
nginx ไม่ต้องเห็นไฟล์เลย จึงไม่ต้องแชร์ volume กัน

### จุดที่พลาดแล้วเจ็บ

**`proxy_buffering off;` กับ `proxy_max_temp_file_size 0;` ไม่ใช่ของแถม**

ถ้าไม่ใส่ nginx จะเขียนไฟล์ที่ดาวน์โหลดลง `proxy_temp_path` ก่อนส่งให้ผู้ใช้ทุกครั้ง
(ยืนยันจาก error log: *"an upstream response is buffered to a temporary file"*)
เท่ากับเขียนดิสก์เพิ่มเต็มขนาดไฟล์ต่อการดาวน์โหลดหนึ่งครั้ง

ตรวจหลัง deploy:

```bash
curl -s https://<host>/dataset/api/health                                    # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/dataset/api/download/keypoints   # 403

TOKEN=$(SECRET_KEY=... python3 scripts/mint_token.py --ttl 300)
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  "https://<host>/dataset/api/download/keypoints?t=$TOKEN"                   # ขนาดต้องตรงกับ manifest
```

Jenkins รันให้อัตโนมัติทุกครั้งที่ deploy ใน stage `Smoke tests`

### สร้างโทเคนสำหรับทดสอบโดยไม่ผ่านฟอร์ม

```bash
SECRET_KEY=... python3 scripts/mint_token.py --ttl 300
```

ใช้ตรวจ deploy โดยไม่ต้องกรอกฟอร์ม — เพราะการกรอกฟอร์มทดสอบทุกครั้งที่ deploy
จะเขียน "คนปลอม" ลงตารางข้อมูลส่วนบุคคลเรื่อย ๆ โทเคนที่สร้างวิธีนี้บันทึกเฉพาะ
สถิติการดาวน์โหลดโดยไม่ผูกกับเจ้าของข้อมูลใด

---

## ตัวแปรสภาพแวดล้อม

| ตัวแปร | ค่าเริ่มต้น | หมายเหตุ |
|---|---|---|
| `SECRET_KEY` | — | **บังคับ** อย่างน้อย 32 ตัวอักษร เปลี่ยนค่า = เพิกถอนโทเคนทุกใบทันที |
| `DATA_DIR` | `/data` | ที่อยู่ของ bundle (mount แบบ read-only) |
| `CATALOG_DIR` | `./data` | ที่อยู่ของ manifest.json / poses.json |
| `DB_PATH` | `$DATA_DIR/db/access.sqlite3` | ต้องเขียนได้ |
| `ROOT_PATH` | ว่าง | ตั้งเป็น `/dataset` เมื่ออยู่หลัง nginx |
| `XACCEL_PREFIX` | `/dataset/_dl` | ใช้เมื่อ `USE_XACCEL=true` เท่านั้น |
| `USE_XACCEL` | `false` | แอปส่งไฟล์เอง ตั้ง `true` เฉพาะถ้าเพิ่ม internal location ใน nginx |
| `TOKEN_TTL_SECONDS` | `86400` | อายุสิทธิ์ดาวน์โหลด |
| `RETENTION_DAYS` | `730` | อายุข้อมูลส่วนบุคคล ลบอัตโนมัติตอนสตาร์ท |
| `RATE_LIMIT_PER_HOUR` | `10` | จำนวนครั้งที่ขอสิทธิ์ได้ต่อ IP ต่อชั่วโมง |

---

## หน้าที่ตาม PDPA

ฟอร์มเก็บอีเมลกับวัตถุประสงค์ = เก็บข้อมูลส่วนบุคคล มีภาระตามกฎหมายตามมา

```bash
D=/srv/ainora/dataset-db/access.sqlite3

python3 scripts/pdpa_tool.py stats   --db $D                    # สถิติภาพรวม
python3 scripts/pdpa_tool.py export  --db $D -o requests.csv    # ส่งออกทั้งหมด
python3 scripts/pdpa_tool.py subject --db $D --email a@b.com    # ขอดูข้อมูลตัวเอง
python3 scripts/pdpa_tool.py erase   --db $D --email a@b.com    # ขอลบ
python3 scripts/pdpa_tool.py purge   --db $D --days 730         # ลบตามระยะเก็บ
```

การลบจะตัด `download_event` ออกจากเจ้าของข้อมูลก่อน (ตั้ง `request_id = NULL`)
แล้วจึงลบ `access_request` สถิติการดาวน์โหลดจึงยังใช้ได้หลังลบข้อมูลส่วนบุคคลไปแล้ว

ระบบจะรัน purge ให้อัตโนมัติทุกครั้งที่บริการสตาร์ท

---

## ค้างอยู่ก่อนเปิดสาธารณะ

ทั้งหมดนี้เป็นเรื่อง **เนื้อหา** ไม่ใช่ระบบ — แก้ที่ `data/manifest.json`
กับ `app/static/privacy.js` แล้ว deploy ใหม่ ไม่ต้องแตะโค้ด

- [ ] **สัญญาอนุญาต** — `dataset.license` ยังเป็น `TBD` รอผู้บริหาร
- [ ] **ประกาศความเป็นส่วนตัว** — `privacy.js` เป็นฉบับร่าง ยังมี `{{...}}` รอเติม และต้องผ่านฝ่ายกฎหมาย
- [ ] **ที่มาภาพต้นฉบับ** — ต้องระบุชื่อหนังสือกับปีที่พิมพ์ เพื่อยืนยันว่าพ้นลิขสิทธิ์แล้ว
- [ ] **ผู้ตรวจสอบท่ารำ** — `REPORT.md` เดิมระบุเองว่าต้องให้ผู้รู้ด้านโนราตรวจก่อนเผยแพร่
- [ ] **ท่าคู่ที่ 07** — ยังจับคู่กับรายชื่อ 12 ท่ามาตรฐานไม่ได้ ดู `poses.json` → `unmapped`
- [ ] **ท่าแมงมุมชักไย (NP012)** — ยังไม่มีภาพซ่อมแซม
- [ ] **ข้อมูลติดต่อและการอ้างอิง** — `dataset.contact` / `dataset.citation` ยังเป็น `TBD`

`validate_catalog.py` จะเตือนทุกข้อที่ยังค้างทุกครั้งที่รัน CI
