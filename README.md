# Google Form Klonlayıcı

Google Form linkini analiz ederek soruları yeniden oluşturan ve cevapları Excel olarak indiren Flask tabanlı uygulama.

## Özellikler
- Matris (grid) soruları (tek seçim / çoklu onay kutusu) desteği
- 'Diğer' seçeneği desteği
- Cevapları Excel (openpyxl) olarak indirme
- Production uyumlu yapı (Gunicorn + ortam değişkeni SECRET_KEY)

## Kurulum (Lokal)
```bash
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # SECRET_KEY değerini değiştir
python app.py
```
Tarayıcı: http://127.0.0.1:5000

## Deploy (Railway / Render / Heroku)
1. Repoyu GitHub'a yükle.
2. Platformda projeyi GitHub'dan bağla.
3. Ortam değişkeni ekle: `SECRET_KEY`
4. Başlatma komutu (Procfile varsa otomatik):  
   ```
   gunicorn app:app --timeout 120 --workers 2
   ```

## Ortam Değişkenleri
| Değişken | Açıklama |
|----------|----------|
| SECRET_KEY | Flask session imzalama anahtarı |

## Notlar
- Google Form'un herkese açık (yanıt verebilir) olması gerekir.
- 403 hatası alırsan farklı hosting veya proxy deneyebilirsin.
