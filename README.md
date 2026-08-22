# Nora Dataset — เว็บเผยแพร่ชุดข้อมูลท่ารำโนรา

หน้าเว็บสองภาษาสำหรับเผยแพร่ชุดข้อมูลโนรา พร้อมระบบขอสิทธิ์ดาวน์โหลด
deploy ด้วย Docker บน `ainora-agent` หลัง nginx ที่มีอยู่เดิม

| | |
|---|---|
| repo | `wachiravit-thitagran/Nora-Dataset` (private) |
| image | `$REGISTRY_URL/diis-itoc/nora-dataset` — build และ push โดย Jenkins ตามแนวเดียวกับ `diis-itoc/psu-policy` |
| URL | `https://<host>/dataset/` |
| port | `127.0.0.1:10095` |

---

## หลักการออกแบบสองข้อ

**1. โค้ดกับข้อมูลอยู่ด้วยกัน หนึ่ง image = หนึ่งชุดข้อมูล**

ไฟล์ zip อยู่ใน repo ที่ `data/bundles/<version>/` และถูก `COPY` เข้า image
image tag เดียวจึงบอกได้ครบว่าโค้ดเวอร์ชันไหนคู่กับข้อมูลชุดไหน ไม่มีขั้นตอนอัปโหลดแยก
ที่จะทำให้สองอย่างหลุดจากกัน และย้อนกลับเวอร์ชันเดิมได้ด้วยการ deploy tag เก่า

ราคาที่จ่ายคือขนาด — ราว 79 MB ต่อเวอร์ชัน เก็บถาวรใน git history และถูกส่งซ้ำทุกครั้งที่ build
แม้แก้แค่โค้ด ถ้าข้อมูลโตกว่านี้มากให้ย้าย `data/bundles/` ออกไปเป็น volume แล้วชี้ `DATA_DIR`
ไปที่นั่น — ตัวแอปอ่านจาก `DATA_DIR` เหมือนเดิม ไม่ต้องแก้โค้ด

**2. nginx จองแค่ `/dataset/` ที่เหลือเป็นเรื่องของแอป**

nginx มี location เดียวและ proxy ทุกอย่างเข้ามา เส้นทางข้างในทั้งหมด —
`/api/catalog`, `/api/access`, `/api/download/{id}`, ไฟล์ static —
จัดการในระดับแอปพลิเคชัน เพิ่ม endpoint ใหม่ได้โดยไม่ต้องแตะ nginx อีกเลย
และ nginx ไม่ต้องเห็นไฟล์ dataset จึงไม่ต้องแชร์ volume กับ container

---

## โครงสร้าง

```
Nora-Dataset/
├── app/
│   ├── config.py            อ่านค่าทั้งหมดจาก environment
│   ├── auth.py              โทเคน HMAC (stateless, หมุน SECRET_KEY = เพิกถอนทุกใบ)
│   ├── db.py                SQLite: access_request + download_event
│   ├── main.py              /api/catalog, /api/access, /api/download/{id}
│   ├── static/              หน้าเว็บที่เสิร์ฟจริง (style.css คือไฟล์ที่ build แล้ว)
│   └── styles/app.css       ต้นทาง Tailwind — แก้ที่นี่แล้วรัน npm run css
├── data/
│   ├── manifest.json        แคตตาล็อก — ขับเคลื่อนทั้งหน้าเว็บ
│   ├── poses.json           ชื่อท่ามาตรฐาน 12 ท่า + aliases + สถานะภาพ
│   └── bundles/<version>/   ไฟล์ zip ที่แพ็กแล้ว — commit เข้า repo และ COPY เข้า image
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

### แก้หน้าตาเว็บ

หน้าเว็บใช้ **Tailwind v4 + daisyUI v5** ชุดเดียวกับ ainora.psu.ac.th
`app/static/style.css` เป็นไฟล์ที่ **build แล้วและ commit ไว้** ตัว image กับตอนรัน
จึงไม่ต้องมี Node เลย แก้ที่ `app/styles/app.css` แล้ว

```bash
npm install        # ครั้งแรกเท่านั้น
npm run css        # build ใหม่
npm run css:watch  # ระหว่างแก้
```

แล้ว **commit `app/static/style.css` ไปด้วยทุกครั้ง** — `validate_catalog.py`
จะเตือนถ้าไฟล์ต้นทางใหม่กว่าไฟล์ที่ build ไว้

---

## แพ็กและเผยแพร่ข้อมูล

```bash
# 1. ดูก่อนว่าจะมีอะไรเข้า bundle บ้าง (ไม่เขียนไฟล์)
python3 scripts/build_bundles.py --dry-run

# 2. แพ็กจริง — เขียนลง data/bundles/<version>/ แล้วอัปเดต data/manifest.json ให้เอง
#    ชุดที่ตั้ง publish:false ใน bundles.config.json จะถูกข้าม
python3 scripts/build_bundles.py

# 3. ตรวจซ้ำว่าไม่มีไฟล์ต้องห้ามหลุดเข้าไป — ห้ามข้ามขั้นนี้
#    สำคัญกว่าเดิมมาก เพราะ commit แล้วลบออกจาก history ไม่ได้
python3 scripts/audit_bundles.py data/bundles/0.1.0-draft

# 4. commit ทั้ง zip และ manifest → merge เข้า main → Jenkins build + deploy
#    ไม่มี rsync แล้ว: ไฟล์เข้า image ไปพร้อมโค้ด
git add data/bundles data/manifest.json
git commit -m "release 0.1.0" && git push
```

`build_bundles.py` ใช้ **whitelist** เท่านั้น ไฟล์จะเข้า bundle ก็ต่อเมื่อ
`bundles.config.json` ระบุชื่อไว้ตรง ๆ หรือระบุโฟลเดอร์พร้อม pattern ที่ตรงกัน
เพราะโฟลเดอร์ต้นทางมีทั้งเอกสาร TOR ใบเสนอราคา invoice และวิดีโอจาก TikTok ปนอยู่
ถ้าใช้ blacklist สักวันจะพลาด

`audit_bundles.py` ตรวจ zip ที่แพ็กเสร็จแล้วอีกชั้นโดยไม่เชื่อ config
เผื่อวันหนึ่งมีคนแก้ config แล้วเผลอเปิดช่อง

---

## ติดตั้งบนเซิร์ฟเวอร์

**ไม่ต้องสร้างโฟลเดอร์อะไรบนเซิร์ฟเวอร์เลย** — ไฟล์ zip อยู่ใน image
ฐานข้อมูลอยู่ใน Docker volume ชื่อ `nora-dataset-db` ที่ Docker สร้างให้เอง
และ compose file รันจาก workspace ของ Jenkins ไม่ได้ก๊อปไปวางบนเครื่อง

เหตุผล: ผู้ใช้ที่ Jenkins agent ใช้รันไม่มีสิทธิ์เขียนใต้ `/srv` และ named volume
ไม่ต้องสร้างไดเรกทอรี ไม่ต้องตั้ง ownership ไม่ต้องขอสิทธิ์ใคร

สิ่งเดียวที่ต้องเตรียมคือความลับสำหรับเซ็นโทเคน

```bash
# ใส่เป็นบรรทัด SECRET_KEY=... ในไฟล์ .env
# แล้วอัปโหลดเป็น Jenkins file credential ชื่อ NORA_DATASET_ENV_PRODUCTION
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

ไฟล์ dataset อยู่**ใน image** nginx ไม่ต้องเห็นไฟล์เลย จึงไม่ต้องแชร์ volume กัน

### จุดที่พลาดแล้วเจ็บ

**`proxy_buffering off;` กับ `proxy_max_temp_file_size 0;` ไม่ใช่ของแถม**

ถ้าไม่ใส่ nginx จะเขียนไฟล์ที่ดาวน์โหลดลง `proxy_temp_path` ก่อนส่งให้ผู้ใช้ทุกครั้ง
(ยืนยันจาก error log: *"an upstream response is buffered to a temporary file"*)
เท่ากับเขียนดิสก์เพิ่มเต็มขนาดไฟล์ต่อการดาวน์โหลดหนึ่งครั้ง

ตรวจหลัง deploy:

```bash
curl -s https://<host>/dataset/api/health                                    # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/dataset/api/download/pose-images   # 403

TOKEN=$(SECRET_KEY=... python3 scripts/mint_token.py --ttl 300)
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  "https://<host>/dataset/api/download/pose-images?t=$TOKEN"                   # ขนาดต้องตรงกับ manifest
```

Jenkins รันให้อัตโนมัติทุกครั้งที่ deploy ใน stage `Deploy to Production`

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
| `DATA_DIR` | `/data` | ที่อยู่ของ bundle — production ตั้งเป็น `/srv/app/data/bundles` (อยู่ใน image) |
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

ฐานข้อมูลอยู่ใน Docker volume จึงต้องรันเครื่องมือ**ข้างในคอนเทนเนอร์**
สคริปต์ติดมากับ image อยู่แล้ว

```bash
P="docker exec ainora-dataset-web python3 scripts/pdpa_tool.py"
D=/var/lib/nora/access.sqlite3

$P stats   --db $D                       # สถิติภาพรวม
$P subject --db $D --email a@b.com       # ขอดูข้อมูลตัวเอง
$P erase   --db $D --email a@b.com       # ขอลบ
$P purge   --db $D --days 730            # ลบตามระยะเก็บ

# ส่งออกเป็นไฟล์: เขียนออก stdout แล้วรับที่เครื่อง
# (คอนเทนเนอร์เป็น read_only เขียนไฟล์ข้างในไม่ได้ ยกเว้น /tmp)
$P export --db $D > requests.csv
```

สำรองฐานข้อมูลก่อนทำอะไรที่ลบข้อมูล

```bash
docker run --rm -v nora-dataset-db:/db -v "$PWD":/out alpine \
  cp /db/access.sqlite3 /out/access-backup-$(date +%F).sqlite3
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
