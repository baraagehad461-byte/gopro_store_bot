# GoPro Store Telegram Bot

بوت متجر الاشتراكات والذكاء الاصطناعي — `@gopro_store_bot`.

## ⚠️ قبل أي push — تأكد إن الكود سليم

```bash
python -m py_compile main.py          # لازم يعدّي بدون أخطاء
python -c "import ast,pathlib; ast.parse(pathlib.Path('main.py').read_text())"
BOT_TOKEN=123456:DUMMY python -c "import main; print('IMPORT OK')"
```

النشر على السيرفر **تلقائي**: أي push على `main` بيتنشر خلال دقيقة.
لو الكود فيه خطأ، **النشر بيترفض والبوت بيفضل شغّال على النسخة القديمة** —
بس من الأفضل تتأكد قبل الـ push.

## التشغيل محليًا

**المتطلبات:** Python 3.11+

1. ثبّت المكتبات:
   ```bash
   pip install -r requirements.txt
   ```
2. جهّز ملف الأسرار:
   ```bash
   cp .env.example .env
   # افتح .env وحدّد BOT_TOKEN (من BotFather) وباقي القيم
   ```
3. شغّل البوت:
   ```bash
   python main.py
   ```

## التشغيل بـ Docker

```bash
docker compose up -d --build
docker logs -f gopro-store-bot
```

## ⚠️ ملاحظة أمنية مهمة

**ممنوع** كتابة توكن البوت داخل الكود. البوت بيقرأه من متغير البيئة `BOT_TOKEN` فقط،
ولو مش موجود بيقف فورًا برسالة واضحة. الملفات `.env` مستثناة من Git عبر `.gitignore`.

لو التوكن اتسرب أو اترفع بالغلط على GitHub — **اعمله revoke فورًا من BotFather** وأنشئ واحد جديد،
لأن أي حد معاه التوكن يقدر يتحكم في البوت بالكامل.

---

## (الأصلي) Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/70a16528-7123-4da8-9883-32c19ca97459

1. Install dependencies: `npm install`
2. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key
3. Run the app: `npm run dev`
