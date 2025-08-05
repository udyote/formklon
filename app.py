# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı - Gelişmiş Sürüm

Bu script, bir Google Form'un yapısını, stilini ve zengin metin içeriğini klonlar.
- Orijinal formun <head> bölümündeki tüm <link> ve <style> etiketlerini alarak görsel tutarlılık sağlar.
- Başlık, açıklama ve sorulardaki zengin metinleri (kalın, italik, altı çizili, linkler, listeler) korur.
- Sorulara eklenmiş görselleri klon forma taşır.
- Çoktan seçmeli, onay kutusu, kısa yanıt, paragraf, açılır liste, matris ve ölçek gibi birçok soru tipini destekler.
- Formdaki bölümleri (sayfaları) mantıksal olarak ayırır.
- "Diğer" seçeneği olan soruları doğru şekilde işler.
- Girilen yanıtları bir Excel dosyası olarak indirir.
"""

import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session
from urllib.parse import unquote

# Flask uygulamasını başlat
app = Flask(__name__)
# Session (oturum) yönetimi için gizli bir anahtar gerekir.
# Geliştirme ortamı için basit bir anahtar yeterlidir.
app.secret_key = os.environ.get("SECRET_KEY", "your-super-secret-key-for-dev")


def analyze_google_form(url: str):
    """
    Verilen Google Form URL'sini analiz eder ve yapısal verilerini çıkarır.

    Args:
        url: Klonlanacak Google Form'un tam veya kısa (forms.gle) URL'si.

    Returns:
        Başarılı olursa {'form_data': dict, 'head_html': str} içeren bir sözlük.
        Hata durumunda {'error': str} içeren bir sözlük döner.
    """
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0.0.0 Safari/537.36')
        }
        # Kısa forms.gle linklerini tam URL'ye çevir
        if 'forms.gle/' in url:
            # allow_redirects=True ile nihai URL'yi al
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
            resp.raise_for_status()
            url = resp.url
        
        # Formun HTML içeriğini çek
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

    except requests.RequestException as e:
        return {"error": f"URL alınırken bir hata oluştu: {e}"}

    soup = BeautifulSoup(resp.text, 'html.parser')

    # --- Stil Bilgilerini (Head) Çek ---
    # Orijinal formun görsel kimliğini korumak için <head> içindeki
    # <link> ve <style> etiketlerini alıyoruz.
    head = soup.head or BeautifulSoup('<head></head>', 'html.parser').head
    head_tags = [str(tag) for tag in head.find_all(['link', 'style'])]
    head_html = '\n'.join(head_tags)

    # --- Form Yapısını (JSON Verisi) Çek ---
    # Formun asıl yapısı, sorular, seçenekler ve ayarlar
    # 'FB_PUBLIC_LOAD_DATA_' adlı bir JavaScript değişkeninde JSON olarak bulunur.
    # Bu, en güvenilir veri kaynağıdır.
    form_data = {'pages': []}
    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                # JavaScript değişkenini temizleyip JSON olarak ayrıştır
                raw_json_str = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw_json_str)

                # Form genel bilgileri
                form_info = data[1]
                # Form başlığı (zengin metin destekli)
                form_data['title'] = form_info[8] or form_info[0] or 'İsimsiz Form'
                # Form açıklaması (zengin metin destekli)
                form_data['description'] = form_info[1] or ''
                
                # Soruların bulunduğu liste
                question_list = form_info[1]

                current_page = []
                # Formun başında e-posta toplama alanı var mı kontrol et
                if data[1][10] and data[1][10][0]:
                    current_page.append({
                        'type': 'E-posta',
                        'text': 'E-posta Adresi',
                        'description': 'Bu form, e-posta adreslerini toplamak üzere ayarlanmış.',
                        'entry_id': 'emailAddress',
                        'required': True
                    })
                
                # Her bir soruyu analiz et
                for q in question_list:
                    # Gerekli bilgiler yoksa atla (bazen boş elemanlar olabilir)
                    if not q or not q[0]:
                        continue

                    question = {}
                    q_id, q_text_plain, q_desc_plain, q_type, q_info = q[0], q[1], q[2], q[3], q[4]

                    # Zengin metin içeren başlık ve açıklamayı al. Yoksa düz metni kullan.
                    rich_text_info = q[-1] if isinstance(q[-1], list) else []
                    question['text'] = rich_text_info[1] if len(rich_text_info) > 1 and rich_text_info[1] else q_text_plain
                    question['description'] = rich_text_info[2] if len(rich_text_info) > 2 and rich_text_info[2] else (q_desc_plain or '')

                    # Sorunun ana görselini bul
                    container = soup.find('div', {'data-item-id': str(q_id)})
                    if container:
                        img_tag = container.select_one('.M7eMe-tJHJj-Lg5QKe img, .geS5n img')
                        question['image_url'] = img_tag['src'] if img_tag else None
                    else:
                        question['image_url'] = None

                    # --- Soru Tiplerine Göre Ayrıştırma ---
                    
                    # Başlık, Resim, Video gibi giriş olmayan elementler
                    if q_info is None:
                        question['type'] = 'Başlık/Medya'
                        current_page.append(question)
                        # Eğer bu eleman bir sayfa sonu (bölüm) ise, yeni sayfaya geç
                        if len(q) > 8 and q[8]:
                            form_data['pages'].append(current_page)
                            current_page = []
                        continue
                    
                    # Giriş gerektiren sorular
                    entry_id = q_info[0][0]
                    question['entry_id'] = f'entry.{entry_id}'
                    question['required'] = bool(q_info[0][2])

                    if q_type == 0: # Kısa Yanıt
                        question['type'] = 'Kısa Yanıt'
                    elif q_type == 1: # Paragraf
                        question['type'] = 'Paragraf'
                    elif q_type == 2 or q_type == 4: # Çoktan Seçmeli (2) veya Onay Kutuları (4)
                        question['options'] = []
                        question['has_other'] = False
                        for opt in q_info[0][1]:
                            if not opt: continue
                            # "Diğer" seçeneği kontrolü
                            if len(opt) > 4 and opt[4]:
                                question['has_other'] = True
                                continue
                            # Seçenek görseli kontrolü
                            img_url = unquote(opt[5][0]) if len(opt) > 5 and opt[5] else None
                            question['options'].append({'text': opt[0], 'image_url': img_url})
                        question['type'] = 'Çoktan Seçmeli' if q_type == 2 else 'Onay Kutuları'
                    elif q_type == 3: # Açılır Liste
                        question['type'] = 'Açılır Liste'
                        question['options'] = [opt[0] for opt in q_info[0][1] if opt and opt[0]]
                    elif q_type == 5: # Doğrusal Ölçek
                        question['type'] = 'Doğrusal Ölçek'
                        question['options'] = [opt[0] for opt in q_info[0][1]]
                        question['labels'] = q_info[0][3] if len(q_info[0]) > 3 and q_info[0][3] else ['', '']
                    elif q_type == 7: # Matris (Çoktan Seçmeli veya Onay Kutusu Tablosu)
                        rows_data = q_info
                        first_row = rows_data[0]
                        question['type'] = 'Onay Kutusu Tablosu' if len(first_row)>11 and first_row[11] and first_row[11][0] else 'Çoktan Seçmeli Tablosu'
                        question['required'] = any(bool(r[2]) for r in rows_data) # Herhangi bir satır zorunluysa zorunludur
                        question['cols'] = [c[0] for c in first_row[1]]
                        question['rows'] = [{'text': r[3][0], 'entry_id': f"entry.{r[0]}"} for r in rows_data]
                    elif q_type == 9: # Tarih
                        question['type'] = 'Tarih'
                    elif q_type == 10: # Saat
                        question['type'] = 'Saat'
                    elif q_type == 18: # Yıldız Derecelendirme
                        question['type'] = 'Derecelendirme'
                        question['options'] = [str(o[0]) for o in q_info[0][1]]
                    else:
                        # Desteklenmeyen veya bilinmeyen soru tipi
                        continue

                    current_page.append(question)
                    
                    # Eğer bu soru bir bölüm sonu ise, yeni sayfaya geç
                    if len(q) > 12 and q[12]:
                        form_data['pages'].append(current_page)
                        current_page = []

                # Döngü bittikten sonra kalan soruları son sayfaya ekle
                if current_page:
                    form_data['pages'].append(current_page)
                
                # JSON verisi başarıyla işlendi, döngüyü sonlandır
                break 

            except (json.JSONDecodeError, IndexError, TypeError) as e:
                return {"error": f"Form verisi ayrıştırılırken bir hata oluştu: {e}. Form yapısı beklenenden farklı olabilir."}
    
    # Hiç soru bulunamazsa hata döndür
    if not form_data['pages'] or not any(form_data['pages']):
        return {"error": "Formda analiz edilecek soru bulunamadı veya form yapısı okunamadı."}

    return {"form_data": form_data, "head_html": head_html}


# --- HTML Şablonu (Jinja2) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Form Klonu</title>
    <!-- Orijinal formun stil ve link etiketleri buraya gelecek -->
    {{ head_html | safe }}
    <!-- Klon için ek özel stiller -->
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #f8f9fa; color: #212529; margin: 0; padding: 1.5rem; }
        .main-container { max-width: 800px; margin: 0 auto; background-color: #ffffff; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        h1, h2 { color: #343a40; }
        .form-title { font-size: 2rem; border-bottom: 1px solid #dee2e6; padding-bottom: 1rem; margin-bottom: 1rem; }
        .form-description { font-size: 1rem; color: #495057; margin-bottom: 2rem; }
        .question-block { margin-bottom: 2rem; padding: 1.5rem; border: 1px solid #e9ecef; border-radius: 6px; }
        .question-text { font-weight: 600; font-size: 1.1rem; margin-bottom: 0.5rem; }
        .question-description { color: #6c757d; font-size: 0.9rem; margin-bottom: 1rem; }
        .required-star { color: #dc3545; margin-left: 4px; }
        .media-image { max-width: 100%; border-radius: 4px; margin-top: 1rem; }
        input[type="text"], input[type="email"], textarea, select { width: 100%; padding: 0.75rem; border: 1px solid #ced4da; border-radius: 4px; box-sizing: border-box; }
        textarea { min-height: 120px; resize: vertical; }
        .option-label { display: block; margin-bottom: 0.5rem; }
        .btn { display: inline-block; font-weight: 600; color: #fff; background-color: #673ab7; border: none; padding: 0.8rem 1.6rem; font-size: 1rem; border-radius: 4px; cursor: pointer; text-align: center; text-decoration: none; margin-top: 1rem; }
        .btn:hover { background-color: #5a319d; }
        .error-message { margin-top: 1rem; color: #dc3545; background-color: #f8d7da; border: 1px solid #f5c2c7; padding: 1rem; border-radius: 4px; }
        table { width:100%; border-collapse:collapse; margin-top:.5rem; }
        th, td { border:1px solid #dee2e6; padding:.6rem; text-align: left; }
        th { background-color: #f8f9fa; }
        td:not(:first-child) { text-align:center; }
    </style>
</head>
<body>
  <div class="main-container">
    <h1>Google Form Klonlayıcı</h1>
    <form method="post" action="/">
      <input type="text" name="url" placeholder="Klonlamak istediğiniz Google Form URL'sini yapıştırın" required>
      <button class="btn" style="background-color: #007bff;">Formu Oluştur</button>
    </form>

    {% if error %}
      <div class="error-message"><strong>Hata:</strong> {{ error }}</div>
    {% endif %}

    {% if form_data %}
      <hr style="margin: 2rem 0;">
      <div class="form-title">{{ form_data.title | safe }}</div>
      {% if form_data.description %}
        <div class="form-description">{{ form_data.description | safe }}</div>
      {% endif %}
      
      <form method="post" action="/submit" enctype="multipart/form-data">
        {% for page in form_data.pages %}
            {% for q in page %}
                <div class="question-block">
                  {% if q.type == 'Başlık/Medya' %}
                    <div class="question-text">{{ q.text | safe }}</div>
                    {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
                  {% else %}
                    <label class="question-text">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</label>
                    {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
                  {% endif %}
                  
                  {% if q.image_url %}<img src="{{ q.image_url }}" class="media-image" alt="Soru görseli">{% endif %}

                  {% if q.type == 'Kısa Yanıt' %}
                    <input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                  {% elif q.type == 'E-posta' %}
                    <input type="email" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                  {% elif q.type == 'Paragraf' %}
                    <textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
                  {% elif q.type == 'Çoktan Seçmeli' or q.type == 'Onay Kutuları' %}
                    <div>
                      {% for opt in q.options %}
                        <label class="option-label">
                          <input type="{{ 'radio' if q.type == 'Çoktan Seçmeli' else 'checkbox' }}" name="{{ q.entry_id }}" value="{{ opt.text }}" {% if q.required and q.type == 'Çoktan Seçmeli' %}required{% endif %}>
                          {{ opt.text | safe }}
                          {% if opt.image_url %}<br><img src="{{ opt.image_url }}" style="max-height: 150px; margin-left: 20px;">{% endif %}
                        </label>
                      {% endfor %}
                      {% if q.has_other %}
                        <label class="option-label">
                            <input type="{{ 'radio' if q.type == 'Çoktan Seçmeli' else 'checkbox' }}" name="{{ q.entry_id }}" value="__other_option__"> Diğer:
                            <input type="text" name="{{ q.entry_id }}.other_option_response" style="width: auto; margin-left: 5px;">
                        </label>
                      {% endif %}
                    </div>
                  {% elif q.type == 'Açılır Liste' %}
                    <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                      <option value="" disabled selected>Bir seçenek belirleyin...</option>
                      {% for opt in q.options %}<option value="{{ opt | safe }}">{{ opt | safe }}</option>{% endfor %}
                    </select>
                  {% elif q.type in ['Çoktan Seçmeli Tablosu', 'Onay Kutusu Tablosu'] %}
                    <table>
                      <thead><tr><th></th>{% for col in q.cols %}<th>{{ col }}</th>{% endfor %}</tr></thead>
                      <tbody>
                        {% for row in q.rows %}
                        <tr>
                            <td>{{ row.text }}</td>
                            {% for col in q.cols %}
                            <td>
                                <input type="{{ 'radio' if 'Çoktan Seçmeli' in q.type else 'checkbox' }}" name="{{ row.entry_id }}" value="{{ col }}">
                            </td>
                            {% endfor %}
                        </tr>
                        {% endfor %}
                      </tbody>
                    </table>
                  {% elif q.type == 'Doğrusal Ölçek' %}
                      <div style="display:flex; justify-content:space-between; align-items:center;">
                          <span>{{ q.labels[0] }}</span>
                          {% for opt in q.options %}
                          <label style="text-align:center;">{{ opt }}<br>
                              <input type="radio" name="{{ q.entry_id }}" value="{{ opt }}" {% if q.required %}required{% endif %}>
                          </label>
                          {% endfor %}
                          <span>{{ q.labels[1] }}</span>
                      </div>
                   {% elif q.type in ['Tarih', 'Saat', 'Derecelendirme'] %}
                       <p><i>Bu soru tipi ({{ q.type }}) şu anda klonda etkileşimli değildir, ancak Excel çıktısında yer alacaktır.</i></p>
                       <input type="hidden" name="{{ q.entry_id }}" value="[Kullanıcıdan alınmadı]">
                  {% endif %}
                </div>
            {% endfor %}
        {% endfor %}
        <button type="submit" class="btn">Yanıtları Excel Olarak İndir</button>
      </form>
    {% endif %}
  </div>
</body>
</html>
"""

# --- Flask Rotaları ---

@app.route('/', methods=['GET', 'POST'])
def index():
    """Ana sayfa. Form URL'sini alır ve klonlanmış formu gösterir."""
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or ('docs.google.com/forms' not in url and 'forms.gle' not in url):
            return render_template_string(HTML_TEMPLATE, error='Lütfen geçerli bir Google Form URL\'si girin.', form_data=None, head_html='')
        
        # Formu analiz et
        result = analyze_google_form(url)
        if 'error' in result:
            return render_template_string(HTML_TEMPLATE, error=result['error'], form_data=None, head_html=result.get('head_html', ''))
        
        form_data = result['form_data']
        head_html = result['head_html']
        
        # Form yapısını session'da sakla ki submit edildiğinde kullanılabilsin
        session['form_structure'] = form_data
        
        return render_template_string(HTML_TEMPLATE, error=None, form_data=form_data, head_html=head_html)
    
    # GET isteği için boş ana sayfayı göster
    return render_template_string(HTML_TEMPLATE, error=None, form_data=None, head_html='')


@app.route('/submit', methods=['POST'])
def submit():
    """Klon formdan gelen yanıtları işler ve Excel dosyası oluşturur."""
    form_structure = session.get('form_structure')
    if not form_structure:
        return 'Hata: Form yapısı oturumda bulunamadı. Lütfen formu tekrar oluşturun.', 400

    answers = request.form
    results = []

    # Kaydedilmiş form yapısına göre cevapları işle
    for page in form_structure.get('pages', []):
        for q in page:
            q_type = q.get('type')
            if q_type in ['Başlık/Medya']:
                continue
            
            entry_id = q.get('entry_id')
            if not entry_id:
                continue

            # BeautifulSoup kullanarak HTML etiketlerini temizle ve soruyu düz metne çevir
            question_text = BeautifulSoup(q['text'], 'html.parser').get_text(separator=' ', strip=True)
            answer_text = 'Yanıtlanmadı'

            if 'Tablosu' in (q_type or ''): # Matris soruları
                row_answers = []
                for row in q.get('rows', []):
                    row_entry_id = row.get('entry_id')
                    row_text = row.get('text')
                    if row_entry_id:
                        # Onay kutusu tablosu birden çok cevap alabilir
                        if 'Onay' in q_type:
                            val = ', '.join(answers.getlist(row_entry_id))
                        else:
                            val = answers.get(row_entry_id, '')
                        if val:
                             row_answers.append(f"{row_text}: {val}")
                answer_text = '; '.join(row_answers) if row_answers else 'Yanıtlanmadı'

            elif q_type == 'Onay Kutuları':
                values = answers.getlist(entry_id)
                final_answers = []
                if '__other_option__' in values:
                    values.remove('__other_option__')
                    # Düzeltilen F-string hatası
                    other_text = answers.get(f"{entry_id}.other_option_response", '').strip()
                    final_answers.append(f"Diğer: {other_text}" if other_text else "Diğer (boş bırakıldı)")
                final_answers.extend(values)
                answer_text = ', '.join(final_answers) if final_answers else 'Yanıtlanmadı'
            
            elif q_type == 'Çoktan Seçmeli':
                value = answers.get(entry_id)
                if value == '__other_option__':
                    other_text = answers.get(f"{entry_id}.other_option_response", '').strip()
                    answer_text = f"Diğer: {other_text}" if other_text else "Diğer (boş bırakıldı)"
                else:
                    answer_text = value or 'Yanıtlanmadı'
            
            else: # Diğer tüm soru tipleri (Kısa Yanıt, Paragraf, vb.)
                answer_text = answers.get(entry_id, '').strip() or 'Yanıtlanmadı'
            
            results.append({'Soru': question_text, 'Cevap': answer_text})
    
    # Sonuçları pandas DataFrame'e çevir
    df = pd.DataFrame(results)
    
    # DataFrame'i Excel dosyasına dönüştürmek için hafızada bir buffer kullan
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Form Yanıtları')
    buf.seek(0)
    
    # Oluşturulan Excel dosyasını kullanıcıya gönder
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'form_yanitlari_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

if __name__ == '__main__':
    # Uygulamayı yerel olarak çalıştırmak için
    # Debug modunu canlı (production) ortamda `False` yapın.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
