# 📧 Daily Email Alerts — Setup Guide

ระบบนี้จะ:
1. ✅ Scan หุ้น S&P 500 / Nasdaq 100 ทุกวัน หลัง US ตลาดปิด
2. ✅ ใช้ **4 strategies**: Near 52W High · Fresh Breakout · **Minervini Trend Template** · **CAN SLIM**
3. ✅ ส่ง HTML email สรุปหุ้นที่เข้าเงื่อนไข BUY พร้อม RS Rating, EPS, Pivot
4. ✅ คุณเอาไป buy/sell เองใน **Webull** หลังตื่นเช้า

> Workflow สำหรับคนไทย: Scanner รันตี 4:30 → email มาถึงตอนคุณตื่น → เปิด Webull ซื้อตามตอนตลาดเปิดถัดไป

---

## 🚀 Step 1: ตั้ง Gmail App Password (10 นาที)

Gmail ไม่อนุญาตให้ Python login ด้วยรหัสผ่านปกติ — ต้องใช้ **App Password** 16 ตัว

### ขั้นตอน

1. **เปิด 2-Step Verification** (จำเป็น)
   - ไปที่ https://myaccount.google.com/security
   - "How you sign in to Google" → **2-Step Verification** → **Turn on**
   - ใส่เบอร์โทร + ยืนยัน OTP

2. **สร้าง App Password**
   - ไปที่ https://myaccount.google.com/apppasswords
   - "Select app" → **Mail**
   - "Select device" → **Other (Custom name)** → พิมพ์ "Stock Scanner"
   - คลิก **Generate**
   - **คัดลอกรหัส 16 ตัว** (เช่น `abcd efgh ijkl mnop`) — เก็บไว้ใช้ต่อ
   - ⚠️ Google จะแสดงครั้งเดียวเท่านั้น

3. **ทดสอบส่งเมล**
   ```powershell
   $env:EMAIL_USER = "your.email@gmail.com"
   $env:EMAIL_PASSWORD = "abcd efgh ijkl mnop"   # 16 ตัว
   $env:EMAIL_TO = "your.email@gmail.com"        # ส่งหาตัวเองได้
   python -c "
   import smtplib
   from email.message import EmailMessage
   import os
   msg = EmailMessage()
   msg['Subject'] = 'Test from Stock Scanner'
   msg['From'] = os.environ['EMAIL_USER']
   msg['To'] = os.environ['EMAIL_TO']
   msg.set_content('ทดสอบ — ถ้าได้รับ = setup สำเร็จ')
   with smtplib.SMTP('smtp.gmail.com', 587) as s:
       s.starttls()
       s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASSWORD'])
       s.send_message(msg)
   print('✅ Email sent')
   "
   ```

   ถ้าเจอ error `(534, b'5.7.9 Application-specific password required')` → ยังไม่ได้สร้าง App Password
   ถ้าเจอ `(535, b'5.7.8 Username and Password not accepted')` → password ผิด

---

## 🧪 Step 2: ทดสอบ Scanner (ก่อนเซต Schedule)

### Dry-run (ไม่ส่งอีเมล — เซฟ HTML เพื่อดูก่อน)
```powershell
cd C:\Users\COJ\Desktop\claude-test\stock-scanner
$env:UNIVERSE = "nasdaq100"
$env:STRATEGY = "all"
python scan_alert.py
# จะสร้าง last_scan.html — ดับเบิ้ลคลิกเปิดในเบราว์เซอร์
```

### ส่งจริงครั้งแรก
```powershell
$env:EMAIL_USER = "your.email@gmail.com"
$env:EMAIL_PASSWORD = "abcd efgh ijkl mnop"
$env:EMAIL_TO = "your.email@gmail.com"
$env:UNIVERSE = "nasdaq100"
$env:STRATEGY = "all"
python scan_alert.py
```

เช็คใน inbox → ควรเห็น email หัวข้อ `🎯 [near_52w_high+...] X BUY signal(s)`

---

## 🔧 Step 3: ตัวเลือก Strategy + Universe

### STRATEGY (เลือก 1 หรือมากกว่า — คั่นด้วย comma)

| ค่า | คำอธิบาย | จำนวน BUY/วัน (โดยประมาณ) |
|----|---------|--------------------------|
| `near_52w_high` | ใกล้ 52W High + Vol สูง (continuation) | 5-20 |
| `fresh_breakout` | เพิ่งทะลุฐานแน่น (early trend) | 0-5 |
| `minervini_tt` | Minervini Trend Template 8 ข้อ | 10-40 |
| `canslim` | O'Neil CAN SLIM (มี EPS check) | 2-10 ⭐ คุณภาพสูง |
| `all` | รันทุกตัว รวมในอีเมลเดียว | - |
| `minervini_tt,canslim` | เฉพาะ 2 อันนี้ (แนะนำ) | - |

**ผมแนะนำ** `STRATEGY=minervini_tt,canslim`
- Minervini = หา momentum leaders (RS rating สูง)
- CAN SLIM = เน้นคุณภาพ (EPS growth + market regime)
- หุ้นที่ขึ้น**ทั้ง 2 รายการ** = highest conviction

### UNIVERSE

| ค่า | จำนวนหุ้น | เวลา scan | เหมาะกับ |
|----|---------|----------|---------|
| `sp500` (default) | 503 | ~2 นาที | ครอบคลุมที่สุด |
| `nasdaq100` | 102 | ~30 วินาที | tech/growth bias |
| `dow30` | 30 | ~15 วินาที | mega-cap conservative |
| `NVDA,AAPL,...` | ตามใส่ | - | ลิสต์เฉพาะ |

---

## ⏰ Step 4: ตั้ง Windows Task Scheduler (รันอัตโนมัติทุกวัน)

### เวลาที่เหมาะ (ประเทศไทย)

| ช่วงปี | เวลา US ปิด (ET) | เวลาไทยที่ scanner ควรรัน |
|-------|----------------|-------------------------|
| มี.ค.-พ.ย. (DST) | 4:00 PM ET | **04:30 น.** |
| ธ.ค.-ก.พ. (no DST) | 4:00 PM ET | **05:30 น.** |

**ผมแนะนำตั้ง 5:00 น.** ครอบคลุมทั้งปี

### สร้าง Task ผ่าน PowerShell (admin)

```powershell
# เปิด PowerShell แบบ Run as Administrator
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -Command `"`$env:EMAIL_USER='your.email@gmail.com'; `$env:EMAIL_PASSWORD='abcd efgh ijkl mnop'; `$env:EMAIL_TO='your.email@gmail.com'; `$env:UNIVERSE='nasdaq100'; `$env:STRATEGY='minervini_tt,canslim'; python C:\Users\COJ\Desktop\claude-test\stock-scanner\scan_alert.py`""

$trigger = New-ScheduledTaskTrigger -Daily -At 05:00
# จันทร์-เสาร์ (ตลาด US เปิด จ.-ศ. → ผลของศุกร์มาเช้าวันเสาร์ไทย)
$trigger.DaysOfWeek = "Tuesday,Wednesday,Thursday,Friday,Saturday"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName "DailyStockScanner" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Scan US stocks + email alerts (Minervini + CAN SLIM)"
```

### ทดสอบ Task ทันที (ไม่รอ 5 โมงเช้า)
```powershell
Start-ScheduledTask -TaskName "DailyStockScanner"
# เช็ค log
Get-ScheduledTask -TaskName "DailyStockScanner" | Get-ScheduledTaskInfo
```

### ตัวเลือก: ใช้ .bat ที่ง่ายกว่า

สร้างไฟล์ `C:\Users\COJ\Desktop\claude-test\stock-scanner\daily_scan.bat`:
```batch
@echo off
set EMAIL_USER=your.email@gmail.com
set EMAIL_PASSWORD=abcd efgh ijkl mnop
set EMAIL_TO=your.email@gmail.com
set UNIVERSE=nasdaq100
set STRATEGY=minervini_tt,canslim
cd /d C:\Users\COJ\Desktop\claude-test\stock-scanner
python scan_alert.py
```

แล้ว schedule ผ่าน GUI:
```powershell
taskschd.msc
```
- Create Basic Task → Daily → 05:00 → Run program → ใส่ path `daily_scan.bat`

---

## 💼 Step 5: Workflow กับ Webull

### Workflow รายวัน
```
04:00 ET (16:00 ET previous day, 04:00 Thai)  ตลาด US ปิด
05:00 Thai     Scanner รันอัตโนมัติ
05:05 Thai     Email มาถึง — มี BUY tickers พร้อม metrics
07:00 Thai     คุณตื่น → เปิด email → review รายชื่อ
07:00-21:00    ระหว่างวัน — ทำการบ้านเพิ่ม:
                - ดู chart pattern จริงใน TradingView
                - ตรวจ news, earnings date
                - เลือก 2-3 ตัวที่มั่นใจที่สุด
21:30 Thai     US ตลาดเปิด (DST) — เปิด Webull ส่ง order
                - Limit order ที่ราคา pivot หรือ +1-2% สูงกว่า
                - ตั้ง Stop Loss ทันที (-7% หรือ -2×ATR)
```

### Order types ที่ใช้ใน Webull

| สถานการณ์ | Order Type | หมายเหตุ |
|----------|-----------|---------|
| ซื้อ near 52W high | **Limit Buy** | ราคา ≤ +1% จาก close ล่าสุด |
| ซื้อ fresh breakout | **Stop Buy** | กระตุ้นที่ราคา pivot |
| Stop loss | **Stop Sell (GTC)** | ตั้งทันทีหลังซื้อ |
| Take profit (Minervini) | **Limit Sell** | +20-25% หรือใช้ trailing |

### ⚠️ ระวังของ Webull
- **Free real-time data ไม่ครบ** (มีดีเลย์ 15 นาทีบางช่วง) → ดู TradingView free แทน
- **Commission $0 จริง** แต่มี SEC/FINRA fees $0.01-0.05/order
- **PDT Rule**: บัญชี < $25k → ทำ day trade ได้แค่ 3 ครั้งใน 5 วัน
  - **Swing trade ไม่ติด PDT** (ถือข้ามคืน)
- **Webull Premium** $30/เดือน → ได้ Level 2 quotes (จำเป็นถ้าเทรดเยอะ)

---

## 🧠 ความเข้าใจ: "Real-time" คืออะไรในบริบทนี้

Scanner นี้ **ไม่ใช่ real-time tick-by-tick** — มันคือ **end-of-day scan** ที่:
- ใช้ราคา close ของวันที่ผ่านมา (Yahoo Finance, ดีเลย์ ~15 นาทีตอนตลาดเปิด, accurate หลังปิด)
- รัน 1 ครั้ง/วัน
- เหมาะกับ **swing trade** (ถือ 5-30 วัน) ตามแนวทาง Minervini/O'Neil

### ทำไมไม่ต้อง intraday?
- Minervini เองยังเน้น **end-of-day setup** — เขาวิเคราะห์ chart ตอนตลาดปิด
- คนไทยถ้าจะเทรด intraday ต้องอยู่ดึก → burn out
- Commission + spread กิน intraday — swing คุ้มกว่า

### ถ้าอยาก intraday scan จริงๆ (ขั้นแอดวานซ์)
- ต้องเสียเงินซื้อ real-time data feed (Polygon.io ~$30/เดือน)
- หรือใช้ TradingView alerts (ฟรี 1 alert, paid plan ~$30/เดือน)
- หรือ TradeStation/IBKR API real-time
- จัดทำได้ — แต่ "ไม่จำเป็น" สำหรับ swing trading style

---

## 📊 อ่านผล Email อย่างไร

### ตัวอย่าง output ของ Minervini Trend Template
```
| Ticker | Close   | % from 52W H | Above 52W L | RS Rating | Pass |
|--------|---------|--------------|-------------|-----------|------|
| NVDA   | $205.10 | -13.3%       | +48%        | 70 🟡      | 8/8  |
| MU     | $864.01 | -20.7%       | +736%       | 99 🟢      | 8/8  |
```

**อ่านอย่างไร:**
- **RS Rating 99** = อยู่ top 1% performance ใน 12 เดือนที่ผ่านมา (เก่งสุด)
- **RS Rating 70-79** = top 21-30% (OK แต่ไม่ดีสุด)
- **% from 52W H -20.7%** = อยู่ต่ำกว่า 52W high 20.7% → ยังมี room
- **Above 52W L +736%** = ขึ้นจาก low 7 เท่า → momentum สุดยอด
- **Pass 8/8** = ผ่านครบทุก Trend Template

### ตัวอย่าง CAN SLIM
```
| Ticker | RS | EPS QoQ | EPS Ann | Rev   | Pass |
|--------|----|---------|---------|-------|------|
| MU     | 99 | +771%   | +756%   | +196% | 6/7  |
| ROST   | 80 | +36%    | +37%    | +21%  | 6/7  |
```

**อ่านอย่างไร:**
- **EPS QoQ +771%** = กำไรไตรมาสล่าสุดโต 771% YoY → Wow! (AI cycle)
- **EPS Annual +37%** = กำไรปีย้อนหลังโต 37% → ผ่าน "A" ใน CAN SLIM
- **Rev +21%** = ยอดขายโต 21% → confirms ของจริง ไม่ใช่ accounting trick
- **Pass 6/7** = ผ่าน CAN SLIM 6 จาก 7 ข้อ (ข้อที่อาจตก = "S" volume แต่ละวัน)

### ⭐ จุดที่ต้องโฟกัส
หุ้นที่อยู่**ทั้ง Minervini + CAN SLIM** = highest conviction
→ ในตัวอย่างข้างต้น: **MU, AMAT, ADI, ROST**

---

## 🛠️ Troubleshooting

| ปัญหา | สาเหตุ | วิธีแก้ |
|------|--------|--------|
| Email ไม่มา | App Password ผิด หรือ env vars ไม่ตั้ง | run dry-run ก่อน เช็ค `last_scan.html` |
| `5.7.9 Application-specific password required` | ใช้ password ปกติ | สร้าง App Password ใหม่ |
| `5.7.14 IP not allowed` | Gmail blocks unusual login | ใส่ App Password แทน + รออีก 10 นาที |
| Task Scheduler ไม่รัน | คอมปิด/sleep | ตั้ง "Wake computer to run" ใน Conditions |
| `possibly delisted: ANSS` | ticker เปลี่ยน symbol | normal — ใน ND > 0 ก็ผ่านได้ |
| BUY = 0 ทุก strategy | regime DOWNTREND, หรือไม่มี setup | ปกติ — บางวันไม่มีสัญญาณ |
| Fundamentals (EPS) เป็น `—` | yfinance ไม่มีข้อมูล ETF / ไม่ใช่หุ้นบริษัท | ปกติสำหรับ ETF |

---

## 🔐 Security Notes

1. **อย่า commit App Password ลง Git**
   - ใช้ env vars เท่านั้น
   - ห้ามใส่ใน `scan_alert.py` ตรงๆ
2. **App Password ใช้แค่ Gmail SMTP** — ใครรู้ก็ login ได้แต่ Gmail
   - **ห้ามใช้กับบัญชี Webull/IBKR**
3. **Revoke App Password ทันที** ถ้าหลุด: https://myaccount.google.com/apppasswords

---

## ✅ Checklist สุดท้าย

- [ ] เปิด 2-Step Verification ใน Google Account
- [ ] สร้าง App Password 16 ตัว — เก็บไว้ใน password manager
- [ ] ทดสอบส่ง test email ผ่าน
- [ ] รัน `scan_alert.py` dry-run ดู `last_scan.html` 
- [ ] รัน scan_alert.py ส่งจริง — เช็คได้รับ email
- [ ] เปิดบัญชี Webull (ถ้ายังไม่มี) + เอกสาร W-8BEN
- [ ] ตั้ง Task Scheduler รันทุกวัน 05:00 น.
- [ ] ทดสอบ Task Scheduler ด้วย "Run" 1 ครั้ง
- [ ] อ่าน Minervini/O'Neil checklist (ดูใน main README)
- [ ] กำหนด position sizing rule (1-2% risk per trade)

เสร็จ! ระบบพร้อมใช้งานจริง 🎯
