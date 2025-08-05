# -*- coding: utf-8 -*-
"""
Google Form Klonlayıcı - Özel Stiller İçin Yapısal Klonlama (Sade Stil)

Bu sürüm, Google Form'un yapısal ve anlamsal içeriğini klonlar.
- Google'ın CSS dosyaları KASTEN ALINMAZ. Bu, formun sizin tarafınızdan
  sağlanan sade stil ile gösterilmesini sağlar.
- Google Form'daki zengin metin (kalın, italik, link, listeler)
  doğru HTML etiketlerine (<b>, <a>, <ul> vb.) dönüştürülür.
- Bu anlamsal etiketler, özel renkler almadan sayfanın temel stilini miras alır.
"""

import os
import io
import json
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_file, session
from urllib.parse import unquote
from datetime import datetime

# Flask uygulamasını başlat
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-super-secret-key-for-dev")


def analyze_google_form(url: str):
    """
    Verilen Google Form URL'sini analiz eder ve yapısal verilerini çıkarır.
    Bu fonksiyon stil bilgilerini (head_html) ÇEKMEZ.
    """
    try:
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0.0.0 Safari/537.36')
        }
        if 'forms.gle/' in url:
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=headers)
            resp.raise_for_status()
            url = resp.url
        
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

    except requests.RequestException as e:
        return {"error": f"URL alınırken bir hata oluştu: {e}"}

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    form_data = {'pages': []}
    for script in soup.find_all('script'):
        if script.string and 'FB_PUBLIC_LOAD_DATA_' in script.string:
            try:
                raw_json_str = script.string.replace('var FB_PUBLIC_LOAD_DATA_ = ', '').rstrip(';')
                data = json.loads(raw_json_str)

                form_info = data[1]
                
                form_data['title'] = form_info[8] if len(form_info) > 8 and form_info[8] else (form_info[0] or 'İsimsiz Form')
                form_data['description'] = form_info[7] if len(form_info) > 7 and isinstance(form_info[7], str) else ''
                
                question_list = form_info[1]

                current_page = []
                if data[1][10] and data[1][10][0]:
                     current_page.append({
                        'type': 'E-posta', 'text': 'E-posta Adresi',
                        'description': 'Bu form, e-posta adreslerini toplamak üzere ayarlanmış.',
                        'entry_id': 'emailAddress', 'required': True
                    })
                
                for q in question_list:
                    if not q or not q[0]: continue

                    question = {}
                    q_id, q_text_plain, q_desc_plain, q_type, q_info = q[0], q[1], q[2], q[3], q[4]

                    rich_text_info = q[-1] if isinstance(q[-1], list) else []
                    question['text'] = rich_text_info[1] if len(rich_text_info) > 1 and rich_text_info[1] else q_text_plain
                    rich_desc = rich_text_info[2] if len(rich_text_info) > 2 and rich_text_info[2] else None
                    question['description'] = rich_desc or q_desc_plain or ''

                    container = soup.find('div', {'data-item-id': str(q_id)})
                    if container:
                        img_tag = container.select_one('.M7eMe-tJHJj-Lg5QKe img, .geS5n img')
                        question['image_url'] = img_tag['src'] if img_tag else None
                    else:
                        question['image_url'] = None

                    if q_info is None:
                        question['type'] = 'Başlık/Medya'
                        current_page.append(question)
                        if len(q) > 8 and q[8]:
                            form_data['pages'].append(current_page)
                            current_page = []
                        continue
                    
                    entry_id = q_info[0][0]
                    question['entry_id'] = f'entry.{entry_id}'
                    question['required'] = bool(q_info[0][2])

                    if q_type == 0: question['type'] = 'Kısa Yanıt'
                    elif q_type == 1: question['type'] = 'Paragraf'
                    elif q_type == 2 or q_type == 4:
                        question['type'] = 'Çoktan Seçmeli' if q_type == 2 else 'Onay Kutuları'
                        question['options'] = []
                        question['has_other'] = False
                        for opt in q_info[0][1]:
                            if not opt: continue
                            if len(opt) > 4 and opt[4]:
                                question['has_other'] = True
                                continue
                            img_url = unquote(opt[5][0]) if len(opt) > 5 and opt[5] else None
                            question['options'].append({'text': opt[0], 'image_url': img_url})
                    elif q_type == 3:
                        question['type'] = 'Açılır Liste'
                        question['options'] = [opt[0] for opt in q_info[0][1] if opt and opt[0]]
                    else:
                        continue
                        
                    current_page.append(question)
                    
                    if len(q) > 12 and q[12]:
                        form_data['pages'].append(current_page)
                        current_page = []

                if current_page:
                    form_data['pages'].append(current_page)
                
                break 

            except (json.JSONDecodeError, IndexError, TypeError) as e:
                return {"error": f"Form verisi ayrıştırılırken bir hata oluştu: {e}."}
    
    if not form_data['pages'] or not any(form_data['pages']):
        return {"error": "Formda analiz edilecek soru bulunamadı veya form yapısı okunamadı."}

    return {"form_data": form_data}


# --- HTML Şablonu (Sizin Belirttiğiniz Sade Stillerle Güncellendi) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Form Klonu</title>
    <!-- 
      Stil Bloğu, istediğiniz sade tasarıma göre güncellendi.
      Anlamsal etiketlere (b, i, a) özel renkler atanmadı.
    -->
    <style>
      body {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        background: #f8f9fa;
        padding: 2rem;
      }
      .container {
        max-width: 760px;
        margin: 0 auto;
        background: #fff;
        padding: 2rem;
        border-radius: 8px;
      }
      .btn {
        background: #198754;
        color: #fff;
        padding: .75rem 1.5rem;
        border: none;
        border-radius: .375rem;
        cursor: pointer;
        font-size: 1rem; /* Okunabilirlik için eklendi */
      }
      .required-star {
        color: #dc3545;
      }

      /* Form elemanları için eklenmiş temel stiller */
      .question-block {
        margin-bottom: 1.5rem;
      }
      .question-text {
        font-weight: 600;
        margin-bottom: 0.5rem;
        display: block; /* Label'ın tam satırı kaplaması için */
      }
      .question-description {
          color: #6c757d;
          font-size: 0.9rem;
          margin-bottom: 0.75rem;
      }
      input[type="text"], input[type="email"], textarea, select {
        width: 100%;
        padding: .5rem;
        border: 1px solid #ccc;
        border-radius: 4px;
        box-sizing: border-box; /* Padding'in genişliği etkilememesi için */
      }
      textarea {
        min-height: 100px;
      }
      .error-message {
        margin-top: 1rem;
        color: red;
      }
    </style>
</head>
<body>
  <div class="container">
    <h1>Google Form Klonlayıcı</h1>
    <form method="post" action="/">
      <input type="text" name="url" placeholder="Google Form URL'si girin" required>
      <button class="btn" style="margin-top:1rem;">Formu Oluştur</button>
    </form>

    {% if error %}
      <div class="error-message"><strong>Hata:</strong> {{ error }}</div>
    {% endif %}

    {% if form_data %}
      <hr style="margin: 2rem 0;">
      <h2 style="margin-top:2rem;">{{ form_data.title | safe }}</h2>
      {% if form_data.description %}
        <div style="margin-bottom:1.5rem;">{{ form_data.description | safe }}</div>
      {% endif %}
      
      <form method="post" action="/submit" enctype="multipart/form-data">
        {% for page in form_data.pages %}
            {% for q in page %}
                <div class="question-block">
                  <label class="question-text">{{ q.text | safe }} {% if q.required %}<span class="required-star">*</span>{% endif %}</label>
                  {% if q.description %}<div class="question-description">{{ q.description | safe }}</div>{% endif %}
                  {% if q.image_url %}<img src="{{ q.image_url }}" style="max-width:100%; border-radius:8px; margin-top:1rem;">{% endif %}

                  {% if q.type == 'Kısa Yanıt' %}<input type="text" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                  {% elif q.type == 'E-posta' %}<input type="email" name="{{ q.entry_id }}" {% if q.required %}required{% endif %}>
                  {% elif q.type == 'Paragraf' %}<textarea name="{{ q.entry_id }}" {% if q.required %}required{% endif %}></textarea>
                  {% elif q.type == 'Çoktan Seçmeli' or q.type == 'Onay Kutuları' %}
                    <div>
                      {% for opt in q.options %}<label style="display:block; margin-bottom:0.5rem;"><input type="{{ 'radio' if q.type == 'Çoktan Seçmeli' else 'checkbox' }}" name="{{ q.entry_id }}" value="{{ opt.text }}"> {{ opt.text | safe }}</label>{% endfor %}
                      {% if q.has_other %}<label style="display:flex; align-items:center; margin-top:0.5rem;"><input type="{{ 'radio' if q.type == 'Çoktan Seçmeli' else 'checkbox' }}" name="{{ q.entry_id }}" value="__other_option__"> Diğer: <input type="text" name="{{ q.entry_id }}.other_option_response" style="width:auto; flex-grow:1;"></label>{% endif %}
                    </div>
                  {% elif q.type == 'Açılır Liste' %}
                    <select name="{{ q.entry_id }}" {% if q.required %}required{% endif %}><option value="" disabled selected>Seçin...</option>{% for opt in q.options %}<option value="{{ opt | safe }}">{{ opt | safe }}</option>{% endfor %}</select>
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

# --- Flask Rotaları (Mantık Değişikliği Yok) ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url or ('docs.google.com/forms' not in url and 'forms.gle' not in url):
            return render_template_string(HTML_TEMPLATE, error='Lütfen geçerli bir Google Form URL\'si girin.', form_data=None)
        
        result = analyze_google_form(url)
        if 'error' in result:
            return render_template_string(HTML_TEMPLATE, error=result['error'], form_data=None)
        
        session['form_structure'] = result['form_data']
        
        return render_template_string(HTML_TEMPLATE, error=None, form_data=result['form_data'])
    
    return render_template_string(HTML_TEMPLATE, error=None, form_data=None)


@app.route('/submit', methods=['POST'])
def submit():
    form_structure = session.get('form_structure')
    if not form_structure:
        return 'Hata: Form yapısı oturumda bulunamadı. Lütfen formu tekrar oluşturun.', 400

    answers = request.form
    results = []
    
    for page in form_structure.get('pages', []):
        for q in page:
            if q.get('type') in ['Başlık/Medya']: continue
            entry_id = q.get('entry_id')
            if not entry_id: continue
            
            question_text = BeautifulSoup(q.get('text',''), 'html.parser').get_text(separator=' ', strip=True)
            answer_text = 'Yanıtlanmadı'

            if q.get('type') == 'Onay Kutuları':
                values = answers.getlist(entry_id)
                final_answers = []
                if '__other_option__' in values:
                    values.remove('__other_option__')
                    other_text = answers.get(f"{entry_id}.other_option_response", '').strip()
                    final_answers.append(f"Diğer: {other_text}" if other_text else "Diğer (boş)")
                final_answers.extend(values)
                answer_text = ', '.join(final_answers) if final_answers else 'Yanıtlanmadı'
            elif q.get('type') == 'Çoktan Seçmeli':
                value = answers.get(entry_id)
                if value == '__other_option__':
                    other_text = answers.get(f"{entry_id}.other_option_response", '').strip()
                    answer_text = f"Diğer: {other_text}" if other_text else "Diğer (boş)"
                else:
                    answer_text = value or 'Yanıtlanmadı'
            else:
                answer_text = answers.get(entry_id, '').strip() or 'Yanıtlanmadı'
            
            results.append({'Soru': question_text, 'Cevap': answer_text})
    
    df = pd.DataFrame(results)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Form Yanıtları')
    buf.seek(0)
    
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'form_yanitlari_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
